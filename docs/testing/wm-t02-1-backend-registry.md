# WM-T02.1 — trwały rejestr backendów tmux

## Reprodukcja i przyczyna

Na kodzie WM-T02 utworzono tymczasowe repozytorium, worktree i proces `sleep` z cwd worktree na prywatnym `tmux -S` poza TMUX_TMPDIR. Sesja miała prawidłowy znacznik workspace. Skan WM zwrócił `False`, bezpośredni odczyt socketu zwrócił `True`, a usunięcie testowego worktree powiodło się mimo żywego PID procesu. Skan opierał się na środowisku procesu, standardowych nazwach i lokalnym dzienniku PID, który nie miał informacji o starszym serwerze.

## Trwały model

Workspace przechowuje `.wm/terminal-backends.json` obok istniejącej ewidencji PID. Zapis atomowy jest serializowany przez dotychczasową blokadę terminalową dla workspace. Rejestr ma wersję, zakres kompletności, opcjonalną preferencję i listę backendów. Losowe ID jest trwałym identyfikatorem powiązania. Instancję serwera rozpoznaje po ścieżce, parze PID/czas startu i urządzeniu oraz inode socketu. Weryfikacja nie próbuje uruchomić nieobecnego serwera.

Dla `-L` nazwa jest rozwiązywana do ścieżki w katalogu tmux przy rejestracji. Dla `-S` wymagany jest absolutny socket bieżącego użytkownika. Zamiana pliku albo instancji nie transferuje własności. Rejestr zapisuje ostatnią zweryfikowaną instancję. Dostępność i własność paneli mają niezależny, bieżący odczyt. Guard zmieniający stan sprawdza tożsamość serwera w kolejce tmux, a klasyfikacja paneli nadal używa WM-T02.

Rejestracja zachowuje inne rekordy i obce pola JSON. Stare workspace bez pliku pozostają dostępne do odczytu i pracy, ale ich inwentarz jest niepełny. Nowe workspace zaczynają od znanego pustego rejestru. Odczyt standardowych nazw i odziedziczonego socketu jest dodatkowym źródłem dowodów przy cleanup. Zachowanie wielu backendów na workspace jest trwałe. Split i zwykłe tworzenie sesji używają wybranego domyślnego backendu; pełne sprawdzanie bezpieczeństwa obejmuje wszystkie. Gdy kilka backendów może obsłużyć ten sam lokalny identyfikator panelu, użytkownik wybiera domyślny backend lub jawny ID w CLI. Wiersz akcji i karta przechowują obserwowaną tożsamość procesu, więc zmiana preferencji nie przekierowuje starego wyboru na inny panel. Split ma jedno miejsce na kartę dla pary workspace i lokalne ID panelu. Otwarcie dwóch paneli o tym samym ID z różnych backendów zastępuje kartę, a oba procesy i rekordy backendów pozostają dostępne. Równoczesne karty z kolidującymi ID pozostają poza zakresem.

## Polecenia

```sh
wm terminal backend-register my-workspace --socket /absolute/legacy.sock
wm terminal backend-register my-workspace --name other-server
wm terminal backend-status my-workspace
wm terminal backend-select my-workspace BACKEND_ID
wm terminal list my-workspace --backend BACKEND_ID
wm terminal attach my-workspace --pane %1 --backend BACKEND_ID
```

Dla historycznych workspace wskaż wszystkie znane backendy. Ostatnią rejestrację wykonaj z `--complete-legacy` i potwierdź zakres inwentarza. Każdy wcześniej zapisany backend zostanie sprawdzony. Potwierdzenie nie pomija niedostępnego rekordu i nie zmienia własności żadnej sesji. Wynik `backend-status` zawiera ID, adres, stan weryfikacji i własność wykrytych paneli.

Jeżeli start zakończy się po rezerwacji rekordu, ale przed potwierdzeniem instancji, wynik pozostaje niepełny. Sprawdź ścieżkę z `backend-status`. Jeśli działa właściwy serwer, zarejestruj istniejącą ścieżkę. Jeśli masz dowód, że zatrzymany start nie pozostawił backendu, uruchom ręcznie neutralną sesję na dokładnej ścieżce, zarejestruj ją i ponów kontrolę. WM nie traktuje samego nieistniejącego pliku socketu jako dowodu ukończonej migracji.

`backend-retire WORKSPACE BACKEND_ID` wymaga jawnego potwierdzenia i obserwacji pustego zakresu. Dla brakującego backendu dopuszcza wyłącznie znany serwer WM z udowodnionym końcem procesu i brakiem zapisanych żywych liderów. Własne, jawne `terminal new` może wznowić zakończony pojedynczy backend w tym samym zakresie dowodów. Zastępczy serwer już obecny na ścieżce nigdy nie zostaje automatycznie przypięty. Archiwizowane ścieżki nadal podlegają bezpiecznej obserwacji, kiedy socket odpowiada.

## Weryfikacja przed zmianą danych

| Wynik | Warunek | Skutek |
|---|---|---|
| VERIFIED_NO_ACTIVE_SESSIONS | Znany inwentarz sprawdzony i brak wskazań na aktywne terminale | Wykonaj pozostałe kontrole Git |
| VERIFIED_ACTIVE_SESSIONS | Żywy panel sesji WM albo wykryty cwd/start katalogu workspace na obserwowanym serwerze | Zablokuj i wskaż socket oraz panele |
| VERIFICATION_INCOMPLETE | Brak istotnego socketu, niezgodność instancji, niepełny inwentarz lub wciąż możliwy żywy PID | Zablokuj z przyczyną |
| VERIFICATION_ERROR | Błędne metadane lub niemożliwy odczyt źródła weryfikacji | Zablokuj |

Decyzja dotyczy całego workspace i jest wykonywana pod dotychczasową blokadą przed usunięciem i ponownie bezpośrednio przed poleceniem Git. Weryfikacja nie zatrzymuje procesów ani nie używa force. Obejmuje znany zakres, a nie dowolne serwery całego systemu. Współdzielone użycie starszej wersji WM zapisującej sesje poza rejestrem nie jest wspierane. Przed operacją destrukcyjną po downgrade wymagane jest ponowne sprawdzenie kompletności pod nadzorem operatora. Ręczne procesy potomne, które odłączyły się od tmux i lidera, nie są wiarygodnie wykrywalne na podstawie tej ewidencji.

## Zakres regresji

Testy używają prywatnych socketów, tymczasowych HOME/XDG i tymczasowych repozytoriów. Testy rejestru obejmują rzeczywiste `-L` i `-S`, ponowny odczyt w niezależnym procesie CLI, legacy, błąd atomowego zapisu, nieprawidłowe ścieżki, zastąpiony socket, równoczesną rejestrację, czysty restart i przerwane tworzenie. Pełna suita obejmuje WM-T01, WM-T02 i Textual.

## Wyniki i decyzja

| Środowisko | Pełny pytest | Ruff, format, mypy |
|---|---|---|
| macOS Intel, Python 3.12.9, tmux 3.8 | 159 testów i 30 subtestów PASS, 273,96 s | PASS |
| Ubuntu 24.04 w Dockerze, Python 3.12.3, tmux 3.4 | 159 testów i 30 subtestów PASS, 181,95 s | PASS |
| Natywne Ubuntu i Apple Silicon | NOT TESTED | NOT TESTED |

Pełne zestawy uruchomiono ponownie po wznowieniu. Objęły regresje WM-T01 i WM-T02. Testy celowane macOS przeszły wcześniej w liczbie 23. Niezależny przegląd zakończył się po trzech rundach bez blokujących uwag w zakresie ochrony worktree.

**WM-T02.1 DONE. WM-T02 DONE w zakresie roadmapy.** Luka starszych, niestandardowych socketów jest domknięta dla objętych kontraktem workspace. Brak potwierdzonego inwentarza skutkuje odmową, a jawnie wskazane serwery są sprawdzane przy cleanup. Równoczesne zakładki z identycznym lokalnym ID z różnych backendów oraz użycie mieszanych wersji pozostają poza zatwierdzonym zakresem. Następne zadanie to WM-T03.
