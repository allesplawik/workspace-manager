# WM-T01 — fokus i potwierdzane przełączanie terminali

## Reprodukcja i przyczyna

Na Ubuntu 24.04 w Dockerze z tmux 3.4 istniejący test `tests/test_integrated_display.py::test_default_wm_shows_home_and_preserves_workspace_processes` ponownie zatrzymał się na `focus dashboard`. Pakiet bajtów `C-b f`, wysłany przez PTY tuż po komendzie shella, trafił do prawego panelu jako `^Bf`. Na tym samym kodzie, obrazie i wersji tmux przeszły dwie próby kontrolne:

- Osobne naciśnięcia prefiksu i klawisza, z potwierdzeniem `client_key_table=prefix` pomiędzy nimi. Cały istniejący test przeszedł w 8,12 s.
- Oryginalny pakiet bajtów z diagnostycznym `assume-paste-time=0` wyłącznie w prywatnej sesji. Cały test przeszedł w 7,40 s. Wartość domyślna wynosiła 1 ms.

To wykazało, że mechanizm szybkiego wklejania w tmux 3.4 powodował ten konkretny błąd testu. Test odtwarza teraz kolejne naciśnięcia i pozostawia ochronę wklejania w aplikacji. Próby nie rozstrzygają wszystkich wcześniej zgłaszanych problemów z fokusem w emulatorach.

Kod miał odrębną lukę. Zmiana panelu wyświetlania i zapis aktywnej karty następowały od razu po utworzeniu procesu klienta tmux. Ta operacja mogła wyprzedzić jego podłączenie. Dla dwóch paneli w jednym workspace nowy klient czekał też na blokadę trzymaną przez dotychczasowego klienta.

## Synchronizacja i granice gwarancji

- Między workspace'ami przygotowywany jest osobny klient w prywatnym oknie. Potwierdzenie wykorzystuje TTY klienta, nazwę sesji, ID okna i panelu oraz jego tożsamość. Stary klient jest dostępny do chwili potwierdzenia, aktywacji wyświetlania i publikacji kart.
- W tym samym workspace używany jest istniejący klient. Przełączenie zmienia cel klienta, a przy błędzie przywraca poprzedni panel i fokus, jeśli cel nadal istnieje. Watchdog sprawdza oczekiwany panel pod tą samą blokadą wyświetlania.
- Do Textual trafia stan odczytany z tmux. Fokus lewego panelu sam w sobie nie zmienia wyświetlanej sesji. Skróty kart na tym samym kliencie tmux mają kolejkę. Textual odrzuca zastąpione żądania przed i po zapisie kart i pomija odświeżenie nieważnego wyniku.
- Nominalne okno oczekiwania na potwierdzenie wynosi 2 s. Pojedyncza komenda z core.run ma własny limit 30 s, a oczekiwanie na istniejącą blokadę wyświetlania jest poza tym oknem. Przy błędzie nie są uruchamiane nowe procesy użytkownika. Sprzątanie dotyczy klienta prywatnego widoku, a nie panelu backendu.
- Przy pierwszym otwarciu istniejącego układu prywatny klient bez metadanych tożsamości wraca do widoku domowego. Zakładkę można otworzyć ponownie, a proces backendu pozostaje. Jeżeli Textual nadal działa w starej wersji, odbiór nowej logiki UI wymaga ponownego uruchomienia samego dashboardu.
- Surowy, zewnętrzny klient tmux nie uczestniczy w blokadzie wyświetlania. Może zmienić wybór po potwierdzeniu, przed kolejnym sprawdzeniem watchdoga. To pozostałe ryzyko WM-T02.

## Regresje

`test_default_wm_shows_home_and_preserves_workspace_processes` korzysta z prawdziwego PTY, osobnego socketu wyświetlania i osobnego TMUX_TMPDIR dla backendu. Sprawdza fokus, resize, mysz, klawiaturę, A → B → A, szybkie przełączanie, brak zmiany PID i duplikatów, zgodność klienta i zakładki oraz zmianę kontekstu sidebaru między workspace'ami. Sprawdza też zamknięcie karty, reconnect, EOF i utrzymanie procesu oraz drzewa sidebaru.

Negatywne przypadki obejmują nieistniejący target, komendę bez zmiany panelu, zajęty klient workspace, zastąpienie żądania po potwierdzeniu oraz w trakcie publikacji i błąd publikacji karty po przygotowaniu nowego klienta. Sprawdzany jest powrót do A i późniejsze udane przełączenie. Testy Pilot sprawdzają wynik prezentacji po błędzie, odrzucenie zastąpionych żądań oraz wyczyszczenie `Opening terminal...` po sukcesie i zastąpienie go błędem przy awarii.

## Odtworzenie i smoke natywnego Ubuntu

Skorzystaj z izolacji opisanej w [baseline](baseline-report.md). W aktywnym venv uruchom `python -m pytest -q`, `ruff check .`, `ruff format --check .` i `mypy src`. Szybka powtórka PTY to `python -m pytest -q tests/test_integrated_display.py`.

Na natywnym Ubuntu utwórz tymczasowe HOME, XDG i TMUX_TMPDIR według procedury baseline. Zainstaluj ten sam kod, uruchom `wm split` bez odziedziczonego TMUX i wybierz dwa testowe shelle. W każdym wypisz `echo $$; pwd` i ustaw inną zmienną. Użyj myszy, kart i skrótu `C-b f`, zmień rozmiar okna i przełącz A → B → A. Sprawdź PID, zmienne i kontekst sidebaru po każdej zmianie oraz po detach i reattach. Zakończ testowy shell przez Ctrl+D. Zweryfikuj pozostały PID i rozwinięcia drzewa. Zakończ wyłącznie zasoby własnej izolacji.

## Wyniki na dostępnych platformach

| Kontrola | Środowisko | Wynik |
|---|---|---|
| Pełny pytest | macOS Intel, Python 3.12.9, tmux 3.8 | 144 testy i 30 subtestów przeszły w 285,53 s |
| Powtórka testów PTY z asercją rzeczywistego wejścia i wyjścia w obu widokach | macOS Intel | 2 testy przeszły w 46,84 s |
| Pełny pytest z końcową asercją PTY | Ubuntu 24.04.5 w Dockerze, Python 3.12.3, tmux 3.4 | 144 testy i 30 subtestów przeszły w 164,31 s |
| Powtórka tego samego PTY | Ubuntu 24.04.5 w Dockerze, Python 3.12.3, tmux 3.4 | 2 testy przeszły w 22,81 s |
| Ruff check, format, mypy | macOS Intel i Ubuntu/Docker | PASS |
| Natywne Ubuntu, Apple Silicon, autoryzowane sesje agentów | Poza tą walidacją | NOT TESTED |

Pełny przebieg macOS dotyczy końcowego kodu produkcyjnego i wcześniejszej wersji asercji PTY. Pierwszy pełny przebieg Ubuntu z tą asercją czekał na domyślny znak promptu, mimo że klient i docelowy panel zostały potwierdzone. Zastąpiono tę zależność testem interakcji. Polecenie wprowadzone przez zewnętrzny PTY musi wytworzyć unikalny tekst zarówno w panelu backendu, jak i w widoku użytkownika.

## Niezależny przegląd

Trzy rundy. Pierwsza wykryła utratę możliwości rollbacku po błędzie zapisu lub renderowania oraz ryzyko publikacji starego żądania. Druga wskazała wyścig w trakcie publikacji. Poprawki obejmują potwierdzenie aktualności przed i po publikacji oraz testy wstrzykniętych błędów. Trzecia nie zgłosiła blokujących uwag do kodu produkcyjnego. Po niej doprecyzowano asercje testowe bez zmiany implementacji.

## Status

**WM-T01 DONE** w zakresie implementacji i walidacji na dostępnych środowiskach. Walidacja wydania na natywnym Ubuntu, Apple Silicon i u rzeczywistych agentów pozostaje NOT TESTED. Następne zadanie to WM-T02, obejmujące współdzielenie tmux z zewnętrznym klientem i szerszą kontrolę własności.
