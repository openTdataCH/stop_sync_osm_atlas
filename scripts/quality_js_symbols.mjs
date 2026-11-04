#!/usr/bin/env node
/**
 * Parse browser scripts for the code map: the functions and classes each file defines, the names it shares with
 * other scripts, the names it reads from them, the URL strings it contains and the HTTP requests it makes.
 *
 * Reads a JSON list of file paths on stdin and writes one JSON object keyed by path. A file that does not parse
 * fails the run: ESLint rejects it too, so the map never silently drops a script.
 */
import { readFileSync } from 'node:fs';
import * as espree from 'espree';
import * as eslintScope from 'eslint-scope';

// Browser scripts share one global scope, reached directly or through these objects.
const GLOBAL_OBJECTS = new Set(['window', 'globalThis', 'self', 'global']);
const JQUERY = new Set(['$', 'jQuery']);
const JQUERY_REQUESTS = new Set(['ajax', 'get', 'getJSON', 'post']);
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

/** The URL argument of ``fetch(url)``, ``$.getJSON(url)`` or ``$.ajax({ url })``, or null when the call is no request. */
function requestUrl(call) {
    const callee = call.callee;
    let jquery = false;
    if (callee.type === 'Identifier') {
        if (callee.name !== 'fetch') return null;
    } else if (callee.type === 'MemberExpression' && !callee.computed && callee.property.type === 'Identifier') {
        const name = callee.property.name;
        const object = callee.object;
        const isJquery = (object.type === 'Identifier' && JQUERY.has(object.name)) || JQUERY.has(globalProperty(object));
        if (name === 'fetch' && isGlobalObject(object)) jquery = false;
        else if (isJquery && JQUERY_REQUESTS.has(name)) jquery = true;
        else return null;
    } else {
        return null;
    }
    const first = call.arguments[0];
    if (!first) return null;
    if (jquery && first.type === 'ObjectExpression') {
        const property = first.properties.find((item) => item.type === 'Property' && !item.computed
            && ((item.key.type === 'Identifier' && item.key.name === 'url') || item.key.value === 'url'));
        return property ? property.value : null;
    }
    return first;
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
    // Local names for a namespace, as ``var namespace = global.MapComponents = ...``.
    const aliases = {};
    const line = (node) => node.loc.start.line;
    const define = (name, node, shared) => {
        symbols.push({ name, line: line(node) });
        if (shared && globals[name] === undefined) globals[name] = line(node);
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
        const topLevel = parent && parent.type === 'Program';
        if (namespaceInit(node)) {
            if (parent && parent.type === 'VariableDeclarator' && parent.id.type === 'Identifier') aliases[parent.id.name] = namespaceInit(node);
        } else if (node.type === 'AssignmentExpression' && member(node.left)) {
            define(member(node.left), node, true);
        } else if (member(node) && !(parent && parent.type === 'AssignmentExpression' && parent.left === node)) {
            references.push({ name: member(node), line: line(node) });
        } else if ((node.type === 'FunctionDeclaration' || node.type === 'ClassDeclaration') && node.id) {
            define(node.id.name, node, topLevel);
        } else if (node.type === 'VariableDeclaration') {
            node.declarations.forEach((declarator) => {
                if (declarator.id.type !== 'Identifier' || (declarator.init && namespaceInit(declarator.init))) return;
                // Every top-level declaration is shared with other scripts; inside a function only functions count.
                if (topLevel || (declarator.init && FUNCTIONS.has(declarator.init.type))) define(declarator.id.name, declarator, topLevel);
            });
        } else if (node.type === 'MethodDefinition' && !node.computed && node.key.type === 'Identifier') {
            define(node.key.name, node, false);
        } else if (node.type === 'AssignmentExpression' && globalProperty(node.left)) {
            define(globalProperty(node.left), node, true);
        } else if (node.type === 'MemberExpression' && globalProperty(node) && !namespaces.has(globalProperty(node))
            && !(parent && parent.type === 'AssignmentExpression' && parent.left === node)) {
            references.push({ name: globalProperty(node), line: line(node) });
        } else if (node.type === 'CallExpression') {
            const url = requestUrl(node);
            if (url) {
                const value = isStringPart(url) ? shape(url) : PLACEHOLDER;
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
        if (!namespaces.has(reference.identifier.name)) references.push({ name: reference.identifier.name, line: line(reference.identifier) });
    });
    return { symbols, globals, references, strings, requests };
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
