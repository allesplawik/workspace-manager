# PoC D — Zakładki terminali

## Architektura

PoC używa dwóch serwerów tmux. Serwer workspace posiada sesje i rzeczywiste PTY. Prywatny serwer widoku składa panel Textual oraz prawy panel, który uruchamia klienta tmux do wybranego PTY. Panele jednego workspace'u mogą współdzielić okno, więc zakładka identyfikuje panel i workspace. Etykieta i okno tmux nie są identyfikatorami.

Pasek jest jednoliniowym statusem u góry prywatnego serwera. Gdy sidebar jest widoczny, początek statusu zajmuje pusta przestrzeń odpowiadająca szerokości lewego panelu. Kliknięcia korzystają z zakresów `range=user`. Textual obsługuje otwieranie formularza i listy globalnej, do których pasek przesyła żądanie. Osobny panel Textual na zakładki wymagałby kolejnego procesu, własnej synchronizacji rozmiaru i fokusu oraz zmiany geometrii zoomu. Zwykłe zakładki okien tmux zmieniałyby jednostkę nawigacji z konkretnego panelu na całe okno oraz nie mogłyby wygodnie objąć różnych workspace'ów.

## Stan i nazwy

- Otwarta lista żyje w opcji sesji prywatnego serwera. Zapis obejmuje kolejność, właściciela, panel, sygnaturę serwera i procesu oraz ostatnią etykietę. UID panelu tmux jest ważny w ramach konkretnego życia serwera. Sygnatura pomaga wykryć ponowne użycie numeru po wymianie procesu.
- Przy pierwszym włączeniu paska widok dodaje istniejące żywe panele zarejestrowanych workspace'ów. Późniejsze uruchomienie UI nie przywraca zakładek celowo zamkniętych.
- Domyślna etykieta to typ agenta i numer wyprowadzony z ID panelu. Numer pozostaje stabilny po zamknięciu innego panelu i może mieć luki. Własna nazwa korzysta z istniejącej opcji panelu `@wm_name`. Puste pole w Rename przywraca etykietę domyślną. Identyczne tytuły nadal mają odrębne klucze i zakresy kliknięć.
- Otwarta zakładka oznacza pozycję w widoku, `connected` oznacza wyświetlany panel, a `live` oznacza działający proces. Wybór innego worktree samodzielnie zmienia zakres sidebaru. Wybór zakładki zmienia ten zakres na podstawie startowego katalogu sesji. Jeżeli filtr Explorera ukrywa cel, jest czyszczony, aby pokazać wybrane worktree.
- Przełączanie zastępuje prawy widok bez wstawiania po drodze powłoki domowej. Słuchacz sidebaru odczytuje zmianę prawego widoku i sprawdza, czy cel nadal jest aktualny, gdy odświeżenie wymaga dodatkowej pracy. Sterownik serializuje modyfikacje zakładek blokadą prywatnego widoku.

## Sterowanie

Kliknięcie etykiety aktywuje panel. `+` otwiera dotychczasowy formularz z bieżącym kontekstem. `⋯` daje dostęp do sesji także wtedy, gdy pasek jest za wąski. Przy przepełnieniu aktualna zakładka pozostaje widoczna. Gdy wszystkie mieszczą się na pasku, zachowują stałą kolejność.

Domyślne skróty po prefiksie `Ctrl+b` to `n` i `p` dla następnej i poprzedniej zakładki, `x` dla zamknięcia aktywnej oraz `+` dla formularza nowej sesji. Własny klawisz układu ma pierwszeństwo nad tymi skrótami. Kliknięcie `×` zamyka wskazaną zakładkę, a środkowy przycisk myszy umożliwia zamknięcie zakładki nieaktywnej. Zamknięcie aktywnej odłącza klienta widoku i pokazuje powłokę domową. Powtórne otwarcie z sidebaru podłącza ten sam proces. Zakończenie sesji pozostaje oddzielną potwierdzaną akcją.

Restart sidebaru oraz odłączenie i ponowne podłączenie prezentacji zachowują zakładki, gdy prywatny serwer tmux nadal działa. Po utracie tego serwera następuje ponowne wykrycie dostępnych paneli. Stan terminala pozostaje własnością tmux. Niedostępna zakładka zgłasza błąd i może zostać zamknięta przez użytkownika. Obserwacja fokusu i podłączania zewnętrznych klientów ma dotychczasowe ograniczenia prywatności sesji.

## Walidacja

Testy Textual rozdzielają wybór worktree od aktywacji terminala oraz sprawdzają aktualizację historii po zmianie zakładki. Testy formatu sprawdzają przepełnienie, zachowanie kolejności i powtarzalne własne nazwy. Test PTY używa izolowanego serwera tmux i faktycznych powłok. Ćwiczy otwieranie z Explorera, skrót następnej zakładki, kliknięcie statusu, zamykanie, ponowne otwarcie, zmianę szerokości oraz detach i reconnect. W otwartym widoku użytkownika potwierdzono również trzy panele Codexa i zachowanie ich PID-ów podczas włączenia paska.

**CONDITIONAL GO.** Status prywatnego tmux pozwala mieć zakładki nad terminalem przy zachowaniu istniejących procesów. Do dalszych prób pozostaje dłuższa praca z zalogowanymi Codex i Claude Code, próby na Linuksie oraz trwałość kolejności po utracie całego prywatnego serwera widoku.

Na macOS przeszło 141 testów i 30 podtestów. Po poprawce bezpośredniego przełączania osobny przebieg pięciu testów zakładek i rzeczywistego tmux też przeszedł, wraz z niezależnym review, Ruff i mypy. Test Ctrl+D potwierdza usunięcie zakończonej zakładki i zachowanie PID sidebaru oraz drugiej powłoki. Gdy serwer backendu jest niedostępny, karta jest usuwana tylko po potwierdzeniu, że zapisany PID nie istnieje.
