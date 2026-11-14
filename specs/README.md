# Workspace Manager v2.0 — pakiet dla Codex

Ten pakiet zastępuje wcześniejsze specyfikacje zakładające modyfikowanie Herdr App. Nowy projekt jest niezależnym menedżerem workspace z terminalami tmux i TUI Textual. Nie jest gotową aplikacją — to specyfikacja implementacyjna.

## Jak użyć

```bash
mkdir -p ~/projects/workspace-manager
cd ~/projects/workspace-manager
codex --add-dir ~/specs/workspace-manager-v2
```

W Codex: `Przeczytaj wszystkie pliki w ~/specs/workspace-manager-v2, zaczynając od CODEX_PROMPT.md. Zaimplementuj kompletny projekt w bieżącym katalogu, iteracyjnie uruchamiaj testy i poprawiaj błędy zgodnie z wymaganiami.`

W razie innej lokalizacji specyfikacji zmień ścieżkę. Repo źródłowe Herdr App nie jest potrzebne.

## Uwaga o terminalu

MVP wykorzystuje tmux jako rzeczywisty terminal i trwały backend. TUI Textual zarządza terminalami i może przełączać/attach do tmux; nie obiecuje renderowania interaktywnego emulatora w panelu Textual.
