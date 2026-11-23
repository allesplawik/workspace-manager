# WM-T02 — własność, blokady i uzgadnianie stanu

Zakres z roadmapy obejmuje WM-SES-04, WM-SES-05 oraz WM-WT-04. Przełączanie i karty WM-T01 są regresją tego zadania. Pracowano w istniejącym worktree z zastanymi zmianami.

## Stan zastany i kontrakt

WM-T01 potwierdzał klienta przy aktywacji. Polecenia na backendzie nadal mogły polegać na domyślnym kliencie lub aktualnym oknie sesji. Znakowanie sesji i wyłączność okna nie dowodziły, kto utworzył panel. Potwierdzenie w Textual nie było związane z instancją procesu. Klient obcy mógł zmienić stan współdzielony, a utrata połączenia mogła zostawić mylącą kartę.

| Zasób | Twórca i dowód | Dozwolone operacje | Sprzątanie |
|---|---|---|---|
| Backendowy socket tmux | Może należeć do użytkownika. Klasyczny tryb zachowuje odziedziczony routing, bez dziedziczenia używany jest standardowy socket. | Odczyt, polecenia na dokładnym zweryfikowanym celu. Ochrona Git obejmuje także nazwane sockety w katalogu tmux użytkownika. | Żadnego `kill-server` w kodzie aplikacji. |
| Prywatny socket wyświetlania | WM tworzy katalog 0700, jawny socket i losowy znacznik zgodny z opcją sesji. | Układ Textual, powłoka domowa, procesy klientów widoku. | Usuń tylko zweryfikowany klient WM. Przy nieudanej inicjalizacji sesję można usunąć po sprawdzeniu znacznika. |
| Sesja backendowa | Dokładna nazwa i `@wm_id` zgodne z rejestrem. Sama nazwa oznacza możliwą kolizję. | Odczyt, dołączenie, tworzenie paneli w zweryfikowanej przestrzeni. | Destrukcyjne żądanie kieruje się do konkretnego panelu, bez kończenia sesji jako jednostki. |
| Klient | Klient widoku jest własnym procesem attach. Odczyt dopasowuje TTY, PID i sesję. | Jawny `switch-client -c` po ponownej kontroli tej tożsamości i wyłączności w kolejce tmux. | Watchdog zwalnia własny proces klienta. Obce klienty pozostają przyłączone. |
| Okno | Powiązanie z dokładną sesją. Wiele wpisów w `window_linked_sessions_list` oznacza okno współdzielone. | Odczyt. Split i wybór konkretnego panelu wymagają zweryfikowanego, niewspółdzielonego okna. | Bez `kill-window` w ścieżce backendu. |
| Panel OWNED | WM stempluje przy utworzeniu `@wm_pane_owner` na podstawie workspace, PID serwera, czasu i ID sesji, ID okna, ID panelu oraz PID procesu. | Odczyt, podłączenie, zmiana nazwy oraz zakończenie po potwierdzeniu. Guard ponawia sprawdzenia w tej samej kolejce tmux. | Dokładny `kill-pane` wyłącznie po zgodności ze znacznikiem i instancją zapamiętaną w dialogu. |
| Panel MANAGED | Prywatny panel ze starszym znacznikiem rodzaju agenta, bez aktualnego znacznika instancji. | Odczyt, podłączenie, nazwa. Zasób nie uzyskuje prawa do zakończenia przez sam odczyt. | Zamknij sam program w terminalu albo świadomie zakończ własny panel przez natywnego klienta tmux. Otwórz nowy terminal WM, aby otrzymać pełny kontrakt. |
| Panel EXTERNAL / UNKNOWN | Obcy lub współdzielony panel, brak wiarygodnego odczytu albo niespójna metryka, np. po respawn. | Obserwacja. Brak przejęcia. | Odmowa zakończenia, przy wyniku niepewnym stan chroniony konserwatywnie. |

Model zabezpiecza przed omyłką i współbieżnym normalnym użyciem tmux. Lokalny użytkownik z dostępem do socketu może wydawać dowolne polecenia i ręcznie fałszować opcje. Opcje tmux nie są granicą uprawnień między użytkownikami.

## Koordynacja i reconciliation

- Blokada rejestru poprzedza blokadę operacji workspace dla remove/unregister. Tworzenie odczytuje aktualny atomowy rejestr pod blokadą workspace, bez ponownego pozyskiwania blokady rejestru. Ochrona worktree jest sprawdzana ponownie przed poleceniem Git.
- Operacje split mają kolejność blokada wyświetlania → krótka blokada workspace, jeżeli potrzebna jest mutacja backendu. Dzierżawa klienta pozostaje odrębna i trwa tak długo jak attach. Proces może odzyskać flock po błędzie, anulowaniu lub śmierci poprzednika. Limity wejścia to pięć sekund dla rejestru, workspace i wyświetlania oraz do dwóch sekund dla dzierżawy wyłącznej. Indywidualne polecenia tmux mają własne limity.
- tmux współdzieli wybrane okno i panel z innymi klientami tej samej sesji. WM odmawia zmiany celu podczas konkurencji. Klient ma być tym samym PID na tym samym TTY i w tej samej sesji także w momencie guardu przed `switch-client`. Istniejący watchdog i odczyt Textual wykrywają rozbieżność bez globalnych hooków. WM oddaje wyłącznie swój widok, usuwa aktywne oznaczenie, pokazuje komunikat i pozostawia sprawdzoną kartę do ponowienia. Nie przywraca starego okna na serwerze zajętym przez obcego klienta.
- Brak socketu ani nowy backend z ponownie użytym ID panelu nie potwierdzają śmierci starego procesu. Przy innym backendzie karta pozostaje, jeśli PID może nadal istnieć. Usuwanie worktree i wyrejestrowanie dodatkowo uwzględniają lokalny zapis PID-ów uruchamianych przez WM.
- Close tab, detach, utrata oglądającego klienta i aktualizacja metadanych nie zabijają procesu PTY. Zakończenie panelu przez UI wymaga weryfikacji przed otwarciem dialogu i ponownie pod blokadą po potwierdzeniu.

## Ograniczenia

Wykrywanie zewnętrznego klienta następuje po obserwacji. Surowe polecenia tmux poza WM mogą zmienić bieżący panel między kolejnymi próbami obserwacji. Zachowanie jest celowo konserwatywne. Kilku klientów tego samego prywatnego układu WM współdzieli jeden dashboard i widok, więc dwa równoległe polecenia sterujące są serializowane, a użytkownik nie otrzymuje osobnych prywatnych widoków.

Ścieżka legacy sprzed ewidencji PID może być niewykrywalna z innego środowiska, jeżeli została uruchomiona na arbitralnym `tmux -S /niestandardowa/ścieżka` spoza standardowego katalogu i poza odziedziczonym `TMUX`. Ewidencja PID chroni znany proces lidera panelu, a nie dowolne procesy potomne odłączone od niego. Ponowne użycie PID może konserwatywnie zablokować operację Git. Start nowego, zewnętrznego procesu niezwiązanego z potwierdzoną sesją tmux nie uczestniczy w locku WM.

Prywatny viewer przejęty ze starszego uruchomienia bez nowego znacznika PID może wymagać jawnego odłączenia i ponownego otwarcia widoku. Kod nie usuwa nienaznaczonego procesu wyświetlania. Stare procesy terminalowe zachowują dotychczasowy PID.

## Scenariusze i polecenia

- IT-001/002/006/009 — `tests/test_tmux_ownership.py`. Utworzenie, stary i obcy panel, kolizja nazwy, respawn, zmiana tożsamości po potwierdzeniu, linkowanie okna między odczytem i operacją w kolejce.
- IT-003/004/005/007/010 — `tests/test_integrated_display.py`. Dwa natywne klienty z prywatnego PTY, odmowa błędnego PID klienta, współdzielona zmiana widoku, zwolnienie własnego klienta, konflikt uruchamianych procesów komend, ponowne otwarcie, zachowane PID.
- IT-008 — sprawdzenie wygaśnięcia flock po przerwaniu procesu i po anulowaniu z wyjątkiem, a także praca na metadanych starszych niż dostępny backend.
- UI — testy Textual potwierdzają odmowę wobec UNKNOWN przed otwarciem dialogu, związanie potwierdzenia ze znacznikiem oraz działanie WM-T01. Komunikat konfliktu sprawdza prawdziwy PTY.

Środowiska izolowano jak w [baseline](baseline-report.md), łącznie z HOME, XDG, TMUX_TMPDIR i prywatnym socketem display. Polecenia `pytest -q`, `ruff check .`, `ruff format --check .` i `mypy src`. Szybkie testy `pytest -q tests/test_tmux_ownership.py tests/test_integrated_display.py tests/test_session_tabs.py`.

## Wyniki i decyzja

| Środowisko | Pełny pytest | Ruff, format, mypy |
|---|---|---|
| macOS Intel, Python 3.12.9, tmux 3.8 | **152 testy i 30 subtestów**, 252,82 s | PASS |
| Ubuntu 24.04 w Dockerze, Python 3.12.3, tmux 3.4 | **152 testy i 30 subtestów**, 183,21 s | PASS |
| Natywne Ubuntu, Apple Silicon | NOT TESTED | NOT TESTED |

Niezależny przegląd miał trzy rundy. W pierwszej poprawiono routing starszych sesji i kod wyniku odmowy attach. W drugiej ujawniono wyścig przy ponownym użyciu TTY. Trzecia zweryfikowała guard PID/TTY/sesja i sprawdzenie własności przy sprzątaniu. Bez otwartych uwag blokujących do przejrzanej implementacji. Autoryzowanych agentów nie uruchamiano.

**WM-T02 PARTIAL.** Zabezpieczenia i regresje przeszły w obu dostępnych środowiskach. Ustalenie wiarygodnej lokalizacji dowolnego starszego backendu spoza standardowego katalogu nadal jest niepełne. Przed WM-T03 należy wprowadzić trwałe wiązanie socketu z workspace oraz jawną procedurę weryfikacji legacy przy operacjach destrukcyjnych. Bez takiego powiązania brak wyniku ze standardowych socketów nie jest dowodem braku starej sesji.
