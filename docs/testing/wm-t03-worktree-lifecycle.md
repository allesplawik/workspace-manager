# WM-T03 — cykl życia worktree

Kod wykorzystuje istniejący Service, Git i ochronę terminali WM-T02.1. Każda zmiana podlega blokadom rejestr → workspace. Usunięcie i jawna zmiana brancha używają tego samego sprawdzenia czystości, tożsamości wspólnego katalogu Git, rejestracji worktree, plików ignorowanych i flag indeksu. Przed mutacją ponownie sprawdzany jest stan terminali. Git wykonuje zmianę bez trybu force, z ochroną plików ignorowanych i z zachowaniem zajętych branchy.

## Użycie i odzyskanie

```sh
wm repo switch WORKSPACE REPO EXISTING_LOCAL_BRANCH
wm repo recover WORKSPACE REPO
wm workspace recover /absolute/path/to/workspace
```

W Explorerze wybierz repo/worktree i akcję „Switch branch” w menu repozytorium. Wpisz istniejący lokalny branch i potwierdź. Akcja sprawdza, czy repo lub HEAD zmieniły się od otwarcia dialogu. Zwykły wybór w drzewie zachowuje branch. `--yes` w CLI stanowi jawne potwierdzenie operacji w automatyzacji.

| Punkt przerwania | Zachowanie |
|---|---|
| Przed trwałym zapisem intencji | Git i zarejestrowany cel pozostają bez zmian. Jeżeli utworzenie workspace przerwano przed zapisaniem metadanych, istniejący katalog jest chroniony przed nadpisaniem i wymaga ręcznej identyfikacji. |
| Po zapisie intencji, przed wykonaniem lub po wykonaniu Git | Stany dodawania, `switching` i `removing` są widoczne w metadanych. `wm repo recover` uzgadnia istniejący, zweryfikowany cel z rzeczywistym HEAD. Gdy dodawanie nie pozostawiło celu lub usunięcie się zakończyło, a Git nie rejestruje celu i brak katalogu, odzyskanie usuwa sam wpis. Niejednoznaczny katalog pozostaje na dysku. |
| Po końcowym zapisie metadanych lokalnych, przed zapisem indeksu | `wm workspace recover PATH` odtwarza indeks z metadanych. Bez zgodności obu kopii terminale pozostają zablokowane. Żadna ścieżka odzyskania nie powtarza automatycznie mutacji Git. |

Identyfikator generacji repo jest opcjonalny przy odczycie dawnego rekordu. Nowe worktrees dostają trwałe ID, co pozwala odrzucić potwierdzenie po ponownym użyciu aliasu. Stare binaria czytające wyłącznie stary schemat repo wymagają powrotu do kopii stanu wykonanej przed aktualizacją.

## Walidacja

- E2E-001 — testy utworzenia i ponownego odczytu, odzyskania utraconego indeksu i zgodności konfiguracji.
- E2E-002 — testy rzeczywistego Git, zachowania plików i branchy, odmowy aktywnego terminala i zajętego brancha, wyraźnego potwierdzenia w CLI i Explorerze i odświeżenia HEAD.
- E2E-009 — awaria po wykonaniu Git przed zapisem końcowym, awaria pomiędzy dwiema kopiami metadanych i odmowa zmiany podmienionego repo. Pełne przebiegi z artefaktu pozostają w WM-T07.

Testy uruchamiano w izolacji tymczasowego HOME, XDG i socketów tmux jak w [baseline](baseline-report.md). Polecenia pełne to `pytest -q`, `ruff check .`, `ruff format --check .` oraz `mypy src`.

| Środowisko | Pełny pytest | Ruff, format, mypy |
|---|---|---|
| macOS Intel, Git 2.50.1, tmux 3.8 | 166 testów i 30 subtestów PASS, 306,95 s | PASS |
| Ubuntu 24.04 w Dockerze, Git 2.43.0, tmux 3.4 | 166 testów i 30 subtestów PASS, 199,58 s | PASS |

Trzy rundy niezależnego przeglądu bez otwartych uwag. Zweryfikowano ochronę przy rozbieżnych metadanych, podmianie repo po otwarciu dialogu oraz odczycie recovery przed konkurencyjnym zapisem. Natywne Ubuntu, Apple Silicon i pełny przebieg z artefaktu RC nie były częścią tej walidacji.

**WM-T03 DONE.** Kolejne zadanie roadmapy to WM-T04, obejmujące już uzgodnioną odmowę cichego zastąpienia karty przy kolizji ID.
