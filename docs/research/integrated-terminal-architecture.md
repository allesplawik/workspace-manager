# PoC D — Workspace Explorer 3.0

Interaktywne `wm` uruchamia prywatny układ tmux z Textual po lewej i powłoką w katalogu domowym po prawej. Ponowne uruchomienie przywraca istniejący widok. `wm split` otwiera ten sam układ, a `wm --classic` udostępnia klasyczny dashboard. Uruchom widok z terminala poza tmux. W obcej sesji tmux dostępny jest tryb klasyczny.

## Uruchomienie z worktree

Użyj Pythona 3.12+ z zależnościami projektu oraz tmux. Z katalogu tego worktree:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/wm
```

Jeśli nadal działa wcześniejsza wersja sidebaru, przełącz fokus na lewy panel (Ctrl+b, f), zakończ Textual klawiszem `q`, odłącz widok (Ctrl+b, d) i uruchom polecenie ponownie. Odnowi się sam sidebar.

## Explorer

Drzewo pokazuje zarejestrowane przestrzenie robocze, grupy według ścieżki repozytorium źródłowego i zarządzane worktree. Wyszukiwanie obejmuje nazwę i ścieżkę workspace'u oraz metadane repozytoriów. Strzałki poruszają się po drzewie, Enter wybiera wiersz, a spacja rozwija lub zwija gałąź. Kropka oznacza żywą sesję. Strzałka oznacza wybrane worktree albo aktualnie wyświetlany terminal. Skrócona etykieta ma pełną treść w podpowiedzi po wskazaniu wiersza.

Menu Explorer zawiera dotychczasowe akcje workspace'u i repozytorium, m.in. tworzenie, dodawanie, status Git i bezpieczne usuwanie. Przed akcją dotyczącą konkretnego worktree wybierz jego wiersz. Nowy terminal podpowiada katalog wybranego worktree. Historia i Memory korzystają z dotychczasowych usług. Rozwiń Memory, aby otworzyć istniejący widok.

## Sesje i skróty

Kliknij sesję lub użyj Enter, aby pokazać istniejący panel. Menu sesji zawiera Open / Focus, Rename, Detach, Terminate i Details. Terminate otwiera potwierdzenie. Detach wraca do powłoki domowej i zostawia proces w tmux. Zakończony panel widoczny w tmux ma stan `ended` i nie można go otworzyć. Jeżeli tmux usunął zakończony panel, znika on po odświeżeniu.

| Skrót | Akcja |
| --- | --- |
| F10 w explorerze | Menu zaznaczonego elementu |
| Ctrl+b, f | Fokus drugiego panelu |
| Ctrl+b, z | Schowaj lub pokaż sidebar |
| Ctrl+b, ← / → | Zmień szerokość |
| Ctrl+b, h | Wróć do domowej powłoki |
| Ctrl+b, d | Odłącz widok |
| Ctrl+b, Ctrl+b | Przekaż prefiks do klienta tmux w prawym panelu |

Szerokość startowa to 36 kolumn. Zakres preferowanej szerokości wynosi 28–50 kolumn, z rezerwą 40 kolumn dla terminala. Poniżej 69 kolumn tmux przechodzi na sam terminal. Po poszerzeniu odzyskuje wcześniejszy wybór układu. Klient z obsługą myszy może przeciągać separator tmux.

Przy starcie można ustawić `WM_EXPLORER_MENU_KEY` (składnia klawiszy Textual, np. `f8`) oraz `WM_SPLIT_FOCUS_KEY`, `WM_SPLIT_TOGGLE_KEY`, `WM_SPLIT_NARROWER_KEY`, `WM_SPLIT_WIDER_KEY`, `WM_SPLIT_HOME_KEY` (litera, cyfra, strzałka lub F1–F12 w składni tmux). Układ używa swojego prefiksu Ctrl+b. Ustawienie klawisza menu dla uruchomionego już sidebaru wymaga ponownego uruchomienia tego sidebaru.

## Punkty integracji

- `cli.py` wybiera tryb. `split.py` zarządza układem, fokusem, szerokością, widocznym klientem i sesją widoku.
- `tui.py` i `dashboard.py` publikują stan z `Service`, `Git`, `Tmux`, `CodexHistory` i `Memory`. Kompaktowe drzewa prezentują dane, a istniejące akcje zachowują wspólną walidację.
- Proces użytkownika i PTY należą do dotychczasowego serwera workspace. Prawy panel uruchamia natywnego klienta do istniejącej sesji. Logikę własności opisuje [tmux-session-ownership.md](tmux-session-ownership.md).
