# PoC D — Hierarchia wizualna Explorera

W poprzednim wariancie typ węzła można było odczytać głównie z wcięcia i obecności chevronu. Identycznie nazwane workspace i worktree łatwo było pomylić. Baseline zapisano bez zmiany danych użytkownika. [28 kolumn przed zmianą](../../features/premium-sidebar/hierarchy-baseline-28.svg)

## Projekt

| Poziom | Oznaczenie |
| --- | --- |
| Workspace | `◫`, niebieska ikona, pogrubiona nazwa i subtelne tło całego wiersza. |
| Repository | `◇`, neutralna ikona i zwykły tekst. Chevron wskazuje możliwość rozwinięcia. |
| Worktree | `⑂`, stonowana nazwa i najgłębsze wcięcie. Zielona kropka oznacza potwierdzoną działającą sesję. |

Fokus klawiatury podświetla cały wiersz. Podkreślenie wskazuje aktywowany workspace lub wybrane worktree. Niebieski tekst worktree jest niezależny od zaznaczenia i wynika z terminala rzeczywiście wyświetlanego po prawej.

Niewielka podklasa istniejącego `ExplorerTree` nakłada tło na gotowy `Strip` Textual. Zachowuje metadane myszy i chevronu. Ikony są jednokolumnowe w badanym środowisku. Jeśli kodowanie wyjścia nie obsługuje ikony, stosowane są `W`, `R`, `Y`. Wygląd symboli zależy od fontu terminala. Pozostałe sekcje, wspólny backend i mechanizm tmux zachowują dotychczasową implementację.

## Obserwacje i testy

Pierwsza iteracja z ikonami ujawniła, że trzykolumnowe wcięcie zabiera miejsce długim nazwom przy 28 kolumnach. Po zmianie na dwukolumnowe wszystkie typy zachowują czytelny układ. Przy 28 kolumnach elipsa może skrócić nazwę lub dodatkowy alias. Kropka sesji zachowuje swoje miejsce. Przy 36 i 50 kolumnach na zrzucie mieści się też alias worktree. Zrzuty Textual pokazują workspace, repozytorium i worktree o identycznej nazwie `source`, wybrany węzeł i osobne worktree podłączonej sesji.

| Szerokość | Textual | Izolowany tmux |
| --- | --- | --- |
| 28 | [SVG](../../features/premium-sidebar/hierarchy-28.svg) | [SVG](../../features/premium-sidebar/hierarchy-tmux-28.svg) |
| 36 | [SVG](../../features/premium-sidebar/hierarchy-36.svg) | [SVG](../../features/premium-sidebar/hierarchy-tmux-36.svg) |
| 50 | [SVG](../../features/premium-sidebar/hierarchy-50.svg) | [SVG](../../features/premium-sidebar/hierarchy-tmux-50.svg) |

Testy Textual weryfikują identyczne oraz długie nazwy, rozwijanie, kolor aktywnego worktree, podkreślenie zaznaczenia oraz pełnowierszowy fokus po resize. Izolowany test prawdziwego tmux potwierdził kliknięcie workspace i kart sesji, przekazanie wejścia do powłoki oraz zachowanie obu procesów. Sprawdzenia wykonano na macOS Intel.

Do następnych iteracji warto zachować jednoznaczne ikony i pełną szerokość tła wyłącznie dla grupy i fokusu. Warto sprawdzić renderowanie w innych emulatorach i fontach terminalowych.

Pełny pytest na macOS — 130 testów i 30 podtestów. Końcową poprawkę fallbacku ikon sprawdzono w trzech testach Textual. Ruff i mypy przeszły. Niezależne review zakończyło się bez otwartych uwag. W działającym oknie potwierdzono wiersze `◫ aaaa → ◇ bookr → ⑂ aaaa` i to samo PID powłoki po odświeżeniu lewego panelu.
