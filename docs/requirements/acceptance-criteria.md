# Kryteria akceptacji WM 3.0

Każdy punkt obowiązuje razem z [Definition of Done](../development/workflow.md). Akceptacja wymaga wyniku z rzeczywistym dowodem. Testy wskazane jako przyszłe są wymaganiami, a ich obecny stan jest w [macierzy](../roadmap/feature-matrix.md).

- **WM-WS-01** — Po restarcie oba tryby pokazują ten sam identyfikator i ścieżkę. Przerwane tworzenie pozostawia stan pozwalający bezpiecznie ponowić lub odzyskać operację. E2E-001.
- **WM-WS-02** — Wyrejestrowanie wymaga potwierdzenia i pozostawia pliki. Odmowa przy repo lub aktywnym procesie obejmuje równoległy start. E2E-001/002.
- **WM-WS-03** — Dopasowanie nazwy lub ścieżki pokazuje oczekiwane gałęzie drzewa. Wybór pozostaje prawidłowy po odświeżeniu lub wraca do jasnego stanu bez wyboru.
- **WM-CFG-01** — Po restarcie wartości są identyczne. Nieobsługiwany schemat zgłasza błąd bez nadpisania. Aktualizacja na kopii danych zachowuje wspierane wpisy.
- **WM-WT-01** — CLI i UI tworzą ten sam wynik w rejestrze i Git. Zajęty branch albo istniejąca ścieżka pozostają nienaruszone. E2E-001/002.
- **WM-WT-02** — Lista i wybór pokazują właściwy branch lub detached HEAD, a otwarcie trafia do wskazanego katalogu. E2E-006.
- **WM-WT-03** — Zmiany staged, untracked, ignored i ścieżki z symlinkiem są chronione. Usunięcie czystego celu zachowuje branch. E2E-002.
- **WM-WT-04** — Aktywny proces lub niepewność blokuje operację. Równoległy start nie omija ochrony pod blokadą workspace. Zaginiony backend z wciąż istniejącym procesem oraz aktywna sesja na nazwanym sockecie blokują zmianę. Historyczne workspace bez potwierdzonego inwentarza pozostają zablokowane. Rejestracja obsługuje -L i -S, utrwala powiązanie po restarcie i zachowuje własność paneli. Zastąpiony lub niedostępny istotny backend daje wynik niepełny, zły rejestr daje błąd. [WM-T02.1](../testing/wm-t02-1-backend-registry.md). E2E-002.
- **WM-WT-05** — Brakujący katalog i przerwany krok mają odrębną diagnozę. Jawne odzyskanie zachowuje istniejące katalogi i branche. E2E-009.
- **WM-WT-06** — Użytkownik jawnie wybiera lokalny branch. Brudne worktree, branch zajęty w innym worktree oraz aktywna lub nierozpoznana sesja powodują odmowę. Po zmianie UI pokazuje zweryfikowany HEAD, a zwykła nawigacja zachowuje dotychczasowy branch.
- **WM-SES-01** — Shell startuje raz w zatwierdzonym cwd i reaguje na wejście. E2E-003/006.
- **WM-SES-02** — Oba programy startują z właściwymi argv i cwd; równoległe terminale mają różne PID. Stub w E2E-003 i osobno smoke agentów.
- **WM-SES-03** — Po przełączeniu A→B→A, także między workspace, zgadzają się PID, cwd, stan i wyświetlany panel. E2E-006.
- **WM-SES-04** — Detach, śmierć klienta i restart Textual przy żywym serwerze pozwalają wrócić do PID i stanu tej samej sesji. Konkurencyjny klient pozostaje podłączony, WM oddaje własny widok i zachowuje kartę do ponowienia. E2E-004.
- **WM-SES-05** — Anulowanie zachowuje procesy. Potwierdzenie odnosi się do tej samej instancji panelu nawet przy zmianie selekcji. Próby wobec MANAGED, EXTERNAL, UNKNOWN lub zastąpionego panelu są odrzucane. E2E-004.
- **WM-SES-06** — Brak celu lub błąd attach daje diagnozę, zachowuje działający poprzedni widok i umożliwia retry bez duplikatu. E2E-009.
- **WM-TAB-01** — Mysz i klawiatura otwierają oraz zmieniają karty również po resize. Zamknięcie ostatniej karty zachowuje PID, a sidebar pozwala otworzyć ją ponownie. E2E-005.
- **WM-TAB-02** — Sidebar, karta i rzeczywisty panel wskazują zgodny cel po zmianie z każdej wspieranej ścieżki. Selekcja w drzewie sama zachowuje aktywny terminal. E2E-006.
- **WM-TAB-03** — Reset i dwa identyczne aliasy nie zmieniają tożsamości. Nazwa przetrwa restart UI i jest zgodna w obu widokach. E2E-008.
- **WM-TAB-04** — Restart UI odtwarza karty w określonej kolejności i pomija tylko definitywnie nieistniejące cele. Utrata serwera widoku ma jawny zakres odzyskania bez przejęcia obcych paneli. E2E-004/009.
- **WM-HIS-01** — Historia stronicuje kandydatów; bieżący kontekst wymaga wiarygodnego cwd, a globalny widok zachowuje nieprzypisane rozmowy.
- **WM-HIS-02** — Alias jest niezależny per provider i ID, przeżywa restart i można go zresetować. Dane providera pozostają bez zmian. E2E-007.
- **WM-HIS-03** — Resume przekazuje dokładne oryginalne ID. Nieznany lub zaginiony kontekst wymaga decyzji, a odmowa zachowuje stan. E2E-007.
- **WM-HIS-04** — Po zatwierdzeniu źródła historia Claude ma filtr, stabilne ID, własne tytuły i pusty stan. Natywny picker przechodzi smoke niezależnie od katalogu.
- **WM-MEM-01** — CLI zapisuje i odczytuje tę samą zawartość co widok Textual. Outdated revision zachowuje nowszy zapis. Zakres pamięci jest widoczny dla użytkownika.
- **WM-MEM-02** — Jeśli wejdzie do zakresu, użytkownik rozpoznaje zakres, dziedziczenie i cel zapisu, a zapis odrębnego zakresu zachowuje pozostałe.
- **WM-UI-01** — Mysz i klawiatura zachowują wybór, dostęp do menu i strukturę drzewa w badanych emulatorach. Nawigacja zachowuje stan Git.
- **WM-UI-02** — Skrót fokusu, mysz, zoom i resize trafiają do oczekiwanego panelu przy 28/36/50 kolumnach sidebaru na obu platformach. E2E-005.
- **WM-CLI-01** — Instalacja udostępnia jawne tryby i podpolecenia z oczekiwanymi exit code oraz formatem danych. Domyślne wejście ma zatwierdzony i przetestowany kontrakt.
- **WM-REL-01** — Wheel zawiera TCSS, czysta instalacja i aktualizacja działają na macOS i Ubuntu. Powrót do poprzedniej wersji jest sprawdzony na kopii stanu.
- **WM-MULTI-01** — Dwa repo w jednym workspace zachowują niezależne branche i katalogi, a zmiana w jednym nie modyfikuje drugiego. Test z dwoma realnymi repo.
- **WM-MULTI-02** — Jawna lista uczestników, niezależne branche, widoczny częściowy błąd i bezpieczne wznowienie bez kasowania innych zasobów. E2E-010.
