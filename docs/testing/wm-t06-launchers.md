# WM-T06 — Konsolidacja launcherów i instalacja

WM-T06 zachowuje routing używany w zintegrowanym worktree. W interaktywnym terminalu `wm` i `wm split` otwierają Explorer z terminalem tmux. `wm --classic` otwiera klasyczny dashboard. Przy przekierowanym stdin lub stdout samo `wm` zachowuje klasyczny fallback. Jawne podpolecenia omijają routing dashboardu.

## Konsolidacja

Zmiana powrotu po wyjściu z shella z rewizji `5aec2c0` jest już obecna funkcjonalnie w zintegrowanym kodzie `Tmux.attach`. Monitorowanie kończy połączenie klienta z wybranym panelem po jego wyjściu. Dwa testy PTY sprawdzają zwykłe okno i podzielone okno oraz dalsze działanie drugiego panelu. Nie trzeba ponownie przenosić tamtego commita.

Metadane pakietu mają wersję deweloperską `3.0.0.dev0`. Wheel udostępnia `wm`, arkusz TCSS i pomocniczy `share/workspace-manager/wm.sh`. Wykonanie `wmcd` we własnym shellu wymaga załadowania tego pliku poleceniem `source` lub `.`. Instrukcja jest w README.

## Walidacja

- Utworzono odizolowane środowisko Python i zbudowano wheel poleceniem `python -m pip wheel --no-deps -w <katalog> .`. Instalacja z pliku wheel i testy odbyły się poza checkoutem. Ponowne zbudowanie wheel z `python -m build --sdist` dało ten sam SHA‑256 `a77a03da5ce54c064bca9180d60d47de3c1d9e3ba94ce3ee3d0d82c655769a7a`.
- Smoke sprawdza `--help`, JSON `doctor` i `workspace status`, TSV `workspace list`, ścieżkę z `workspace select --print-path`, exit 1 przy brakującym workspace i exit 2 przy błędzie składni. `wmcd` zmienia katalog nadrzędnego shella. Przy nieznanym workspace zachowuje katalog i zwraca błąd.
- W PTY sprawdzono start zainstalowanych `wm`, `wm --classic` i `wm split` i poprawne zakończenie lub detach. Testy używają odrębnego HOME, XDG oraz prywatnych socketów tmux.
- Test `tests/test_interfaces.py::CLITests::test_default_launcher_routing_preserves_classic_and_subcommands` weryfikuje oba warunki TTY, flagę klasyczną, pominięcie dashboardu dla podpoleceń i jawny launcher split.
- Wyniki platform podaje [raport bazowy](baseline-report.md).

## Bramka następnego etapu

Artefakt dev0 służy walidacji WM-T06. WM-T07 obejmuje utrwalenie konkretnego revision dla Feature Freeze, budowę artefaktów RC, migrację i powrót na kopii konfiguracji, ręczną walidację zalogowanych agentów odłożoną z WM-T05 oraz decyzję Release Ready. Szczegóły określa [Release Contract](../release/3.0.0-release-contract.md).

Niezależny review potwierdził zgodność routingu z kodem, zawartość wheel oraz obecność obu scenariuszy powrotu z shella. Uwagi blokujące nie wystąpiły.
