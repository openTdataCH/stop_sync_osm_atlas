# Common LaTeX Compilation Errors and How to Avoid Them

## 1. Math Mode Errors

### Error: "Missing $ inserted"

**What it means:** LaTeX is interpreting something as math when it shouldn't be, or you have unmatched math delimiters.

**Common causes:**
- Using special characters like `_`, `^`, `#`, `&`, `%` outside of math mode or `\texttt{}`
- Unmatched braces `{}` 
- Incorrect use of `\verb` commands with pipe characters `|`
- Using `\_` inside `\texttt{}` instead of `\textunderscore`

**Solutions:**

#### For underscores in code/technical text:
```latex
% WRONG:
\texttt{highway=bus\_stop}

% CORRECT:
\texttt{highway=bus\textunderscore stop}
```

#### For special characters in regular text:
```latex
% WRONG:
This costs $50 & is 100% guaranteed

% CORRECT:
This costs \$50 \& is 100\% guaranteed
```

#### For `\verb` commands:
```latex
% WRONG (can cause issues with multiple on same line):
\verb|text1| and \verb|text2|

% BETTER:
\texttt{text1} and \texttt{text2}
```

---

## 2. Special Characters

### Characters that need escaping:
- `#` → `\#`
- `$` → `\$` 
- `%` → `\%`
- `^` → `\^{}`
- `&` → `\&`
- `_` → `\_` (in regular text) or `\textunderscore` (in `\texttt{}`)
- `~` → `\~{}`
- `{` → `\{`
- `}` → `\}`

### Safe handling of underscores:
```latex
% In regular text:
This is a file\_name.txt

% In \texttt (recommended):
\texttt{file\textunderscore name.txt}

% In math mode (different purpose):
$x_1 + x_2$
```

---

## 3. Citation and Reference Errors

### Error: "Citation 'key' undefined"
**Cause:** Bibliography key doesn't exist or bibliography not processed
**Solution:** 
1. Check that the citation key matches exactly in your `.bib` file
2. Run the full compilation sequence: `pdflatex` → `biber` → `pdflatex` → `pdflatex`
3. Use latexmk for automatic handling: `latexmk -pdf document.tex`

### Error: "Reference 'label' undefined"
**Cause:** Label doesn't exist or hasn't been processed yet
**Solution:**
1. Verify the label exists: `\label{your-label}`
2. Run compilation twice for cross-references to resolve
3. Check for typos in `\ref{your-label}` vs `\label{your-label}`

---

## 4. Compilation Sequence Issues

### The Right Way to Compile:

#### For documents WITH bibliography:
```bash
# Manual sequence:
pdflatex document.tex
biber document      # or bibtex document
pdflatex document.tex
pdflatex document.tex

# Automatic (recommended):
latexmk -pdf document.tex
```

#### For documents WITHOUT bibliography:
```bash
pdflatex document.tex
pdflatex document.tex  # Second run for cross-references
```

---

## 5. File and Path Issues

### Error: "File not found"
**Common causes:**
- Incorrect relative paths to images/files
- Missing file extensions
- Case sensitivity on Linux/Mac

**Solutions:**
```latex
% WRONG:
\includegraphics{Images/MyImage}

% CORRECT:
\includegraphics{images/myimage.png}

% GOOD PRACTICE (no extension needed if properly set):
\graphicspath{{images/}}
\includegraphics{myimage}
```

---

## 6. Float and Figure Issues

### Error: "Too many unprocessed floats"
**Cause:** Too many figures/tables without text between them
**Solution:**
```latex
% Add occasionally:
\clearpage

% Or use:
\FloatBarrier  % requires \usepackage{placeins}
```

### Warning: "Float too large for page"
**Solution:**
```latex
% Resize the content:
\includegraphics[width=0.8\textwidth]{image}

% Or allow page break:
\begin{figure}[!ht]  % Note the !
```

---

## 7. Encoding Issues

### Error: Strange characters or "Invalid UTF-8"
**Solutions:**
1. Save files as UTF-8 encoding
2. Add to preamble:
```latex
\usepackage[utf8]{inputenc}
\usepackage[T1]{fontenc}
```

---

## 8. Verbatim and Code Issues

### Problems with `\verb`:
1. Cannot be used in arguments to other commands
2. Can cause issues with multiple uses on same line
3. Pipe `|` characters can conflict

**Safer alternatives:**
```latex
% Instead of \verb:
\texttt{code\textunderscore here}

% For larger code blocks:
\begin{verbatim}
code here
\end{verbatim}

% With syntax highlighting:
\usepackage{listings}
\begin{lstlisting}
code here
\end{lstlisting}
```

---

## 9. Best Practices for Error Prevention

### 1. Structure your document properly:
```latex
\documentclass[options]{class}
% Preamble with all \usepackage commands
\usepackage{...}

\begin{document}
% Content here
\end{document}
```

### 2. Use consistent conventions:
- Always use `\texttt{}` for inline code instead of `\verb`
- Use `\textunderscore` for underscores in `\texttt{}`
- Keep citations and labels short and simple
- Use hyphens instead of underscores in labels: `\label{fig:my-image}` not `\label{fig:my_image}`

### 3. Test compilation frequently:
- Compile after major changes
- Use version control to track working states
- Keep backups of working versions

### 4. Handle special content carefully:
```latex
% URLs:
\usepackage{url}
\url{http://example.com/path_with_underscores}

% Code files:
\usepackage{listings}
\lstinputlisting{code.py}

% Math:
$equation\_with\_subscripts$  % Only in math mode
```


## Summary

Most LaTeX errors are preventable with:
1. **Proper escaping** of special characters
2. **Consistent use** of `\texttt{}` instead of `\verb`
3. **Correct compilation sequence** (especially for bibliography)