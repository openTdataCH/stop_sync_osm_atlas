#!/usr/bin/env node
/**
 * Parse browser scripts for the code map: the functions and classes each file defines, the names it shares with
 * other scripts, the names it reads from them, the URL strings it contains, the HTTP requests it makes and how often
 * it spells each name. A name read is placed in the function or class around it, and a call or reference to a
 * function or class of the same file is a link between the two.
 *
 * Reads a JSON list of file paths on stdin and writes one JSON object keyed by path. A file that does not parse
 * fails the run: ESLint rejects it too, so the map never silently drops a script.
 */
import { readFileSync } from 'node:fs';
import * as espree from 'espree';
import * as eslintScope from 'eslint-scope';

// Browser scripts share one global scope, reached directly or through these objects.
const GLOBAL_OBJECTS = new Set(['window', 'globalThis', 'self', 'global']);
const PLACEHOLDER = '{}';
const FUNCTIONS = new Set(['FunctionExpression', 'ArrowFunctionExpression', 'ClassExpression']);

function walk(node, visit, parent) {
    if (!node || typeof node.type !== 'string') return;
    visit(node, parent);
    for (const key of Object.keys(node)) {
        if (key === 'loc' || key === 'range') continue;
        const value = node[key];
        if (Array.isArray(value)) value.forEach((child) => walk(child, visit, node));
        else if (value && typeof value.type === 'string') walk(value, visit, node);
    }
}

function isGlobalObject(node) {
    return node.type === 'Identifier' && GLOBAL_OBJECTS.has(node.name);
}

/** ``window.name`` or ``global.name``: the shared global ``name``. */
function globalProperty(node) {
    return node.type === 'MemberExpression' && !node.computed && isGlobalObject(node.object) && node.property.type === 'Identifier'
        ? node.property.name : null;
}

/** The text a string expression evaluates to, with ``{}`` for every part known only at runtime. */
function shape(node) {
    if (node.type === 'Literal' && typeof node.value === 'string') return node.value;
    if (node.type === 'TemplateLiteral') {
        return node.quasis.map((quasi, index) => quasi.value.cooked + (index < node.expressions.length ? PLACEHOLDER : '')).join('');
    }
    if (node.type === 'BinaryExpression' && node.operator === '+') return shape(node.left) + shape(node.right);
    return PLACEHOLDER;
}

function isStringPart(node) {
    return (node.type === 'Literal' && typeof node.value === 'string') || node.type === 'TemplateLiteral'
        || (node.type === 'BinaryExpression' && node.operator === '+');
}

/** ``SharedUtils``, directly or through ``window`` or ``global``. */
function isSharedUtils(node) {
    return (node.type === 'Identifier' && node.name === 'SharedUtils') || globalProperty(node) === 'SharedUtils';
}

/**
 * The URL argument of ``fetch(url)``, ``SharedUtils.fetchJson(url)`` or a page's own ``fetchJson(url)`` wrapper,
 * or null when the call is no request.
 */
function requestUrl(call) {
    const callee = call.callee;
    let isRequest = false;
    if (callee.type === 'Identifier') {
        isRequest = callee.name === 'fetch' || callee.name === 'fetchJson';
    } else if (callee.type === 'MemberExpression' && !callee.computed && callee.property.type === 'Identifier') {
        const name = callee.property.name;
        isRequest = (name === 'fetch' && isGlobalObject(callee.object)) || (name === 'fetchJson' && isSharedUtils(callee.object));
    }
    return isRequest ? call.arguments[0] || null : null;
}

/** The name a function is defined under: its own, the variable it is assigned to, or the property, as ``fetchJson``. */
function functionName(node, parent) {
    if (node.id) return node.id.name;
    if (parent && parent.type === 'VariableDeclarator' && parent.id.type === 'Identifier') return parent.id.name;
    const left = parent && parent.type === 'AssignmentExpression' ? parent.left : null;
    return left && left.type === 'MemberExpression' && left.property.type === 'Identifier' ? left.property.name : null;
}

/** ``global.Name = global.Name || {}``: several scripts add members to one shared object, so ``Name`` is a namespace. */
function namespaceInit(node) {
    if (node.type !== 'AssignmentExpression' || !globalProperty(node.left)) return null;
    const name = globalProperty(node.left);
    const right = node.right;
    const same = (side) => globalProperty(side) === name || (side.type === 'Identifier' && side.name === name);
    return right.type === 'LogicalExpression' && (right.operator === '||' || right.operator === '??') && same(right.left)
        && right.right.type === 'ObjectExpression' ? name : null;
}

function analyze(text, ast, namespaces) {
    const scopes = eslintScope.analyze(ast, { ecmaVersion: 2022, sourceType: 'script' });
    const symbols = [];
    const globals = {};
    const references = [];
    const strings = [];
    const requests = [];
    // Links inside the file: from a function or class (or the file, as null) to a function or class it calls or names.
    const links = [];
    // Local names for a namespace, as ``var namespace = global.MapComponents = ...``.
    const aliases = {};
    // Each symbol's source range; the declaration node a scope variable is defined by, and the top-level
    // declarations by name, for resolving references to symbols.
    const ranges = [];
    const byNode = new Map();
    const topLevelNames = {};
    const parents = new Map();
    // How often the file spells each name, declarations included: a function no file spells again is unused. Names
    // inside strings count, because markup built in a string calls functions, as ``onclick="filterByRoute(...)"``.
    const mentions = Object.create(null);
    const mention = (name) => { mentions[name] = (mentions[name] || 0) + 1; };
    const line = (node) => node.loc.start.line;
    /**
     * A request inside a wrapper is no blind spot of its own: its URL is the wrapper's parameter, or the wrapper is
     * ``fetchJson`` itself, and every caller of the wrapper is read on its own line.
     */
    const inWrapper = (call, url) => {
        for (let node = parents.get(call); node; node = parents.get(node)) {
            if (!/Function/.test(node.type)) continue;
            if (functionName(node, parents.get(node)) === 'fetchJson') return true;
            if (url.type === 'Identifier' && node.params.some((param) => param.type === 'Identifier' && param.name === url.name)) return true;
        }
        return false;
    };
    const define = (name, node, shared, options = {}) => {
        // Callable: a function or class. Any other shared value, as the object a script publishes, is not.
        const index = symbols.push({ name, line: line(node), callable: Boolean(options.callable) }) - 1;
        ranges.push(node.range);
        if (options.declaration) byNode.set(options.declaration, index);
        if (options.topLevel && topLevelNames[name] === undefined) topLevelNames[name] = index;
        if (shared && globals[name] === undefined) globals[name] = line(node);
    };
    /** The innermost symbol whose source holds ``node``, or null at file level. */
    const enclosing = (node) => {
        let found = null;
        ranges.forEach((range, index) => {
            if (range[0] <= node.range[0] && node.range[1] <= range[1] && (found === null || ranges[found][0] <= range[0])) found = index;
        });
        return found;
    };
    /** The namespace ``node`` names: ``MapComponents``, ``global.MapComponents`` or a local alias. */
    const namespaceOf = (node) => {
        const name = globalProperty(node) || (node.type === 'Identifier' ? aliases[node.name] || node.name : null);
        return namespaces.has(name) ? name : null;
    };
    /** ``MapComponents.MapCore``: a namespace member, shared under its qualified name. */
    const member = (node) => node.type === 'MemberExpression' && !node.computed && node.property.type === 'Identifier' && namespaceOf(node.object)
        ? namespaceOf(node.object) + '.' + node.property.name : null;
    walk(ast, (node, parent) => {
        parents.set(node, parent);
        if (node.type === 'Identifier') mention(node.name);
        const quoted = node.type === 'TemplateElement' ? node.value.cooked : node.type === 'Literal' && typeof node.value === 'string' ? node.value : '';
        (quoted.match(/[A-Za-z_$][\w$]*/g) || []).forEach(mention);
        const topLevel = parent && parent.type === 'Program';
        if (namespaceInit(node)) {
            if (parent && parent.type === 'VariableDeclarator' && parent.id.type === 'Identifier') aliases[parent.id.name] = namespaceInit(node);
        } else if (node.type === 'AssignmentExpression' && member(node.left)) {
            define(member(node.left), node, true, { callable: FUNCTIONS.has(node.right.type) });
        } else if (member(node) && !(parent && parent.type === 'AssignmentExpression' && parent.left === node)) {
            references.push({ name: member(node), line: line(node), node });
        } else if ((node.type === 'FunctionDeclaration' || node.type === 'ClassDeclaration') && node.id) {
            define(node.id.name, node, topLevel, { callable: true, declaration: node, topLevel });
        } else if (node.type === 'VariableDeclaration') {
            node.declarations.forEach((declarator) => {
                if (declarator.id.type !== 'Identifier' || (declarator.init && namespaceInit(declarator.init))) return;
                // Every top-level declaration is shared with other scripts; inside a function only functions count.
                const isFunction = Boolean(declarator.init && FUNCTIONS.has(declarator.init.type));
                if (topLevel || isFunction) define(declarator.id.name, declarator, topLevel, { callable: isFunction, declaration: declarator, topLevel });
            });
        } else if (node.type === 'MethodDefinition' && !node.computed && node.key.type === 'Identifier') {
            define(node.key.name, node, false, { callable: true });
        } else if (node.type === 'AssignmentExpression' && globalProperty(node.left)) {
            define(globalProperty(node.left), node, true, { callable: FUNCTIONS.has(node.right.type) });
        } else if (node.type === 'MemberExpression' && globalProperty(node) && !namespaces.has(globalProperty(node))
            && !(parent && parent.type === 'AssignmentExpression' && parent.left === node)) {
            references.push({ name: globalProperty(node), line: line(node), node });
        } else if (node.type === 'CallExpression') {
            const url = requestUrl(node);
            const value = url && isStringPart(url) ? shape(url) : PLACEHOLDER;
            if (url && !(value.startsWith(PLACEHOLDER) && inWrapper(node, url))) {
                requests.push({ line: line(node), url: value.startsWith(PLACEHOLDER) ? null : value,
                    expression: text.slice(url.range[0], url.range[1]).replace(/\s+/g, ' ').slice(0, 120) });
            }
        }
        // A string is recorded once, at the top of its concatenation, when it starts with a path.
        if (isStringPart(node) && !(parent && parent.type === 'BinaryExpression' && parent.operator === '+')) {
            const value = shape(node);
            if (value.startsWith('/') && !value.startsWith('//') && value.length > 1) strings.push({ value, line: line(node) });
        }
    });
    // Names a file reads but does not declare come from the shared global scope: another script, or the browser.
    // A namespace itself is no one script's export; its members are.
    scopes.globalScope.through.forEach((reference) => {
        if (!namespaces.has(reference.identifier.name)) references.push({ name: reference.identifier.name, line: line(reference.identifier), node: reference.identifier });
    });
    // A read of a function or class declared in this file links the symbol around it to that declaration. Inside a
    // function eslint-scope resolves the name; a script's top-level declarations are globals, left unresolved.
    const link = (identifier, target) => {
        const source = enclosing(identifier);
        if (target === undefined || !symbols[target].callable || source === target) return;
        const parent = parents.get(identifier);
        const called = parent && (parent.type === 'CallExpression' || parent.type === 'NewExpression') && parent.callee === identifier;
        links.push({ source, target, kind: called ? 'calls' : 'uses', line: line(identifier) });
    };
    scopes.scopes.forEach((scope) => scope.references.forEach((reference) => {
        if (reference.resolved && !reference.isWriteOnly() && reference.resolved.defs.length) link(reference.identifier, byNode.get(reference.resolved.defs[0].node));
    }));
    scopes.globalScope.through.forEach((reference) => {
        if (!reference.isWriteOnly()) link(reference.identifier, topLevelNames[reference.identifier.name]);
    });
    return {
        symbols, globals, strings, requests, links, mentions,
        references: references.map(({ name, line: at, node }) => ({ name, line: at, symbol: enclosing(node) }))
    };
}

const paths = JSON.parse(readFileSync(0, 'utf8'));
const parsed = [];
for (const path of paths) {
    const text = readFileSync(path, 'utf8');
    try {
        parsed.push({ path, text, ast: espree.parse(text, { ecmaVersion: 'latest', sourceType: 'script', loc: true, range: true }) });
    } catch (error) {
        process.stderr.write(`${path}: ${error.message}\n`);
        process.exit(1);
    }
}
// A namespace is recognised in any script, so a script that only reads ``MapComponents.MapCore`` is linked too.
const namespaces = new Set();
parsed.forEach(({ ast }) => walk(ast, (node) => {
    if (namespaceInit(node)) namespaces.add(namespaceInit(node));
}));
const result = {};
parsed.forEach(({ path, text, ast }) => { result[path] = analyze(text, ast, namespaces); });
process.stdout.write(JSON.stringify(result));
