\NeedsTeXFormat{LaTeX2e}
\ProvidesClass{sn-jnl}[2026/05/20 Local Springer Nature compatible template class]
\LoadClass[11pt]{article}

\RequirePackage[margin=1in]{geometry}
\RequirePackage[numbers,sort&compress]{natbib}
\RequirePackage{amsthm}
\RequirePackage{etoolbox}
\RequirePackage{ifthen}
\RequirePackage{url}
\RequirePackage{hyperref}
\RequirePackage{titlesec}
\RequirePackage{enumitem}
\RequirePackage{booktabs}
\RequirePackage{rotating}

\setlength{\parindent}{1.5em}
\setlength{\parskip}{0pt}

\newtheoremstyle{thmstyleone}{3pt}{3pt}{\itshape}{} {\bfseries}{.}{.5em}{}
\newtheoremstyle{thmstyletwo}{3pt}{3pt}{}{} {\bfseries}{.}{.5em}{}
\newtheoremstyle{thmstylethree}{3pt}{3pt}{}{} {\bfseries}{.}{.5em}{}

\newcommand{\fnm}[1]{#1}
\newcommand{\spfx}[1]{#1}
\newcommand{\sur}[1]{#1}
\newcommand{\sfx}[1]{#1}
\newcommand{\orgdiv}[1]{#1}
\newcommand{\orgname}[1]{#1}
\newcommand{\orgaddress}[1]{#1}
\newcommand{\street}[1]{#1}
\newcommand{\city}[1]{#1}
\newcommand{\postcode}[1]{#1}
\newcommand{\state}[1]{#1}
\newcommand{\country}[1]{#1}
\newcommand{\bmhead}[1]{\subsection*{#1}}
\newcommand{\backmatter}{}
\newcommand{\botrule}{\bottomrule}
\newcommand{\pacs}[2][]{\par\noindent\textbf{#1:} #2\par}
\newcommand{\unnumbered}{\setcounter{secnumdepth}{0}}

\newcommand{\sn@titletext}{}
\newcommand{\sn@shorttitle}{}
\newcommand{\sn@authorlist}{}
\newcommand{\sn@affillist}{}
\newcommand{\sn@abstracttext}{}
\newcommand{\sn@keywordtext}{}
\newcommand{\sn@pendingemail}{}
\newcommand{\sn@pendingequal}{}

\renewcommand{\title}[2][]{\gdef\sn@shorttitle{#1}\gdef\sn@titletext{#2}}
\renewcommand{\author}{\@ifstar\sn@authorstar\sn@authornostar}
\newcommand{\sn@authorstar}[2][]{\sn@addauthor{#1}{#2}}
\newcommand{\sn@authornostar}[2][]{\sn@addauthor{#1}{#2}}
\newcommand{\sn@addauthor}[2]{%
  \gappto\sn@authorlist{\par\textbf{#2}\ifstrempty{#1}{}{\textsuperscript{#1}}\sn@pendingemail\sn@pendingequal}%
  \gdef\sn@pendingemail{}\gdef\sn@pendingequal{}%
}
\newcommand{\email}[1]{\gappto\sn@authorlist{\,\texttt{#1}}}
\newcommand{\equalcont}[1]{\gappto\sn@authorlist{\par\emph{#1}}}
\newcommand{\affil}{\@ifstar\sn@affilstar\sn@affilnostar}
\newcommand{\sn@affilstar}[2][]{\sn@addaffil{#1}{#2}}
\newcommand{\sn@affilnostar}[2][]{\sn@addaffil{#1}{#2}}
\newcommand{\sn@addaffil}[2]{\gappto\sn@affillist{\par\ifstrempty{#1}{}{\textsuperscript{#1}}#2}}
\renewcommand{\abstract}[1]{\gdef\sn@abstracttext{#1}}
\newcommand{\keywords}[1]{\gdef\sn@keywordtext{#1}}

\renewcommand{\maketitle}{%
  \begin{center}
    {\LARGE\bfseries \sn@titletext\par}\vspace{1em}
    {\sn@authorlist\par}\vspace{0.75em}
    {\small\sn@affillist\par}
  \end{center}
  \vspace{1em}
  \noindent\textbf{Abstract}\par\smallskip\noindent\sn@abstracttext\par\medskip
  \noindent\textbf{Keywords:} \sn@keywordtext\par\bigskip
}

\bibliographystyle{plainnat}