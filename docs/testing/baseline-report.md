# Baseline PoC D przed WM 3.0

Badany kod to bieżący worktree `experiment/integrated-terminal-workspace` na `5dfa1e5` wraz z zastanym niezacommitowanym PoC D. Stan `main` z `5aec2c0` nie został użyty jako substytut wykonywanych testów.

| Kontrola | Środowisko | Wynik |
|---|---|---|
| Pełne `python -m pytest -q` | macOS Intel, Darwin 24.6, Python 3.12.9, Git 2.50.1 Apple, tmux 3.8 | **PASS** — 141 testów i 30 subtestów, bez pominięć, 211,83 s |
| Ruff check, Ruff format --check, mypy | macOS, konfiguracja projektu | **PASS** — format 28 plików, mypy 14 plików |
| Instalacja z pakietu, `wm --help`, `wm doctor` | Ubuntu 24.04.5 LTS w Dockerze, Python 3.12.3, Git 2.43.0, tmux 3.4 | **PASS** — help/doctor z zainstalowanego entrypointu bez PYTHONPATH, bez Codex/Claude i uv |
| Pełne `pytest -q` | Ten sam kontener Ubuntu | **FAIL** — 140 przeszło, 1 nie przeszedł, 30 subtestów przeszło, bez pominięć, 154,60 s |
| Izolowane powtórzenie nieudanego testu | Ubuntu 24.04.5 LTS w nowym kontenerze, tmux 3.4 | **FAIL** — ten sam krok focus, 13,34 s |
| Natywne Ubuntu, macOS Apple Silicon, interaktywna macierz emulatorów i autoryzowane smoke agentów | Poza tym uruchomieniem | **NOT TESTED** |

## Historyczne niepowodzenie baseline

`tests/test_integrated_display.py::test_default_wm_shows_home_and_preserves_workspace_processes` na Ubuntu nie otrzymał aktywacji lewego panelu w ciągu 12 s. Oczekiwano `pane_active=1` dla sidebaru. Końcówka wyjścia PTY zawierała `^Bf` przy prompcie shella po prawej. To dowód porażki routingu w scenariuszu testowym. W WM-T01 odtworzono to zachowanie i odizolowano przyczynę w sposobie dostarczania skrótu w teście. Odpowiednie wymagania to WM-UI-02, WM-TAB-02 i WM-SES-06. Próby kontrolne, poprawki i wyniki po zmianie są w [raporcie WM-T01](wm-t01-focus-regression.md).

## Odtworzenie i zakres dowodu

Na macOS użyto istniejącego środowiska zależności Python i bieżących źródeł. W obu środowiskach usunięto `TMUX` i `TMUX_PANE`, podano osobne `HOME`, `CODEX_HOME`, `XDG_CONFIG_HOME`, `XDG_STATE_HOME` i `TMUX_TMPDIR`. Ubuntu użyło kopii źródeł i testów z montowania tylko do odczytu. Testy uruchamiały prawdziwe tymczasowe repozytoria i tmux oraz kontrolowane klienty PTY. Agentów nie logowano, nie używano danych użytkownika ani opłat. Nie włączono narzędzia pomiaru coverage.

Najważniejsze braki to diagnoza przyczyny awarii fokusu, pełne przejście wielokontekstowe, rzeczywiste resume obu agentów oraz instalacja i interakcja na docelowych platformach. [Strategia](test-strategy.md) definiuje dalsze bramki. [Scenariusze](e2e-scenarios.md) odróżniają przypadki planowane od obecnych testów.

## Procedura ponownego uruchomienia

Identyfikator badanych wejść to `cd45ee524e6957d68124f7a894987223369a0e18885b76c8795e7874379f62c5`. To SHA-256 listy posortowanych ścieżek `src/**/*.py`, `src/**/*.tcss`, `tests/**/*.py` i `pyproject.toml` w rekordach złożonych ze ścieżki, spacji, SHA-256 i końca wiersza. Uwzględnia bieżące niezacommitowane pliki.

Z katalogu PoC D, z aktywnym venv projektu na macOS, zapisz ścieżkę interpretera i uruchom testy z krótką ścieżką bazową dla socketów.

```sh
wm_audit_python="$(command -v python)"
wm_audit_root="$(mktemp -d /tmp/wma.XXXXXX)"
mkdir "$wm_audit_root"/{home,config,state,tmux}
env -u TMUX -u TMUX_PANE HOME="$wm_audit_root/home" \
  CODEX_HOME="$wm_audit_root/home/codex" XDG_CONFIG_HOME="$wm_audit_root/config" \
  XDG_STATE_HOME="$wm_audit_root/state" TMUX_TMPDIR="$wm_audit_root/tmux" \
  PYTHONPATH=src "$wm_audit_python" -m pytest -q
ruff check .
ruff format --check .
mypy src
```

Ubuntu można odtworzyć w jednorazowym kontenerze. Pakiety pobierane z rejestrów mogą zmienić wersję. Porównaj wypisane wersje z baseline.

```sh
docker run --rm -v "$PWD:/audit:ro" ubuntu:24.04 bash -ec '
  apt-get update -qq && apt-get install -y -qq python3-venv git tmux
  mkdir /tmp/wma && cd /tmp/wma && cp -r /audit/{src,tests,pyproject.toml,README.md} .
  python3 -m venv .venv
  . .venv/bin/activate
  pip install "textual>=8.2.8,<9" "typer>=0.12,<1" pytest pytest-asyncio hatchling
  mkdir home config state tmux
  export HOME="$PWD/home" CODEX_HOME="$PWD/home/codex"
  export XDG_CONFIG_HOME="$PWD/config" XDG_STATE_HOME="$PWD/state" TMUX_TMPDIR="$PWD/tmux"
  unset TMUX TMUX_PANE PYTHONPATH
  python --version && git --version && tmux -V
  pip install --no-build-isolation --no-deps .
  wm --help && wm doctor
  PYTHONPATH=src pytest -q
'
```

Aby powtórzyć sam błąd, dodaj do pytest selektor `tests/test_integrated_display.py::test_default_wm_shows_home_and_preserves_workspace_processes`.

## Wyniki po stabilizacji

Wyniki po WM-T01 i WM-T02 są osobnymi przebiegami tego worktree. [WM-T01](wm-t01-focus-regression.md) dokumentuje przyczynę historycznego błędu fokusu. [WM-T02](wm-t02-ownership-reconciliation.md) dokumentuje testy własności, dwa klienty i ograniczenia wykrywania sesji legacy.

[WM-T02.1](wm-t02-1-backend-registry.md) rozszerza powtórkę o trwałość adresów `-L` i `-S`, blokadę niepełnej weryfikacji i odtworzenie błędu przy aktywnym worktree.

Pełny przebieg po wznowieniu WM-T02.1 dał 159 testów i 30 subtestów PASS na macOS Intel oraz Ubuntu 24.04 w Dockerze. Ruff, formatowanie i mypy przeszły na obu platformach.

[WM-T03](wm-t03-worktree-lifecycle.md) rozszerza regresję o zmianę brancha i awarie zapisów. Oba środowiska ukończyły 166 testów i 30 subtestów.

[WM-T04](wm-t04-session-tabs.md) zweryfikowano na macOS Intel i Ubuntu 24.04 w Dockerze. Na każdym środowisku przeszło 167 testów i 30 subtestów.

[WM-T05](wm-t05-history-resume.md) rozszerza testy o historię, resume i weryfikację worktree. Pełne przebiegi przed końcową poprawką zamykania Textual dały po 173 testy i 30 subtestów PASS na macOS Intel z tmux 3.8 oraz Ubuntu 24.04 w Dockerze z tmux 3.4. Ruff, formatowanie i mypy przeszły na obu platformach. Po poprawce test spóźnionego podświetlenia przeszedł na obu platformach, a na macOS przeszło także siedem wybranych testów UI. Autoryzowane smoke rzeczywistych rozmów pozostają otwarte.

[WM-T06](wm-t06-launchers.md) zweryfikowano z tego samego wheel `3.0.0.dev0` w czystych środowiskach macOS Intel 15.8.3 z tmux 3.8 i Ubuntu 24.04 Docker z tmux 3.4. Na obu platformach PASS dla CLI, Bash i Zsh `wmcd`, trzech interaktywnych wejść w PTY oraz ukierunkowanej regresji routingu i powrotu po zamknięciu shella (3 testy, 5 subtestów). To dowód deweloperski przed walidacją właściwego RC.
