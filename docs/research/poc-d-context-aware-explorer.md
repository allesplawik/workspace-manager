# PoC D — Context-Aware Workspace Explorer

## Cel

Po wybraniu worktree Explorer ma prowadzić do powiązanego terminala albo rozmowy. Istniejący Textual zarządza lewym panelem, tmux obsługuje prawdziwy terminal po prawej. Eksperyment pozostaje w tym samym worktree i korzysta z istniejących modeli, pamięci, mechanizmu uruchamiania i własności sesji.

## Kontekst, terminale i pamięć

- Aktywowanie worktree dodaje nagłówek z nazwą źródłowego repozytorium i branchem. Wybór workspace'u pokazuje jego zakres i wszystkie należące do niego terminale. Grupa źródłowa używa kontekstu nadrzędnego. Przy braku wyboru działa globalne menu i nie pojawiają się przypisane wiersze.
- Lokalna lista pokazuje panele uruchomione w wybranym worktree lub jego podkatalogu. Powiązanie korzysta z ścieżki startowej tmux i z bieżącej ścieżki tylko wtedy, gdy tmux nie udostępnia ścieżki startowej. Przycisk tworzenia podpowiada katalog worktree w istniejącym formularzu. Sam wybór nie uruchamia agenta ani nie zmienia brancha.
- **All sessions** pokazuje panele wszystkich zarejestrowanych workspace'ów dostępnych w tmux. Pozycja ma właściciela i identyfikator panelu. Wybór używa istniejącego podłączenia. Stan `connected` odzwierciedla widok po prawej, `live` działający panel, a `ended` panel zakończony i zachowany przez tmux.
- **Workspace Memory** otwiera dotychczasowy widok na poziomie workspace'u. Nie przypisuje treści pamięci do konkretnego worktree.

## Historia i tytuły

W sidebarze są najwyżej cztery ostatnie rozmowy Codexa o dokładnie pasującej, kanonicznej ścieżce roboczej. Samo podobieństwo nazwy repozytorium lub tytułu nie wystarcza. Lokalna historia jest pobierana przez istniejące `thread/list` z filtrem cwd i sprawdzana ponownie po stronie WM.

**View all conversations** używa tego samego protokołu bez filtra cwd. Pokazuje także rekordy z nieznanym, usuniętym lub niezarządzanym katalogiem. Można zawęzić listę do workspace'u, grupy worktree tego samego repozytorium lub konkretnego worktree i wyszukać po tytule własnym lub oryginalnym w załadowanych stronach. Przycisk **More** pobiera kolejną stronę. Meta w pełnym widoku pomaga rozróżniać identyczne tytuły. Jeśli katalog wybranej rozmowy nie należy jednoznacznie do istniejącego workspace'u, wznowienie w aktualnym kontekście wymaga potwierdzenia.

Kod projektu nie udostępnia listowania historii Claude Code. Filtr Claude pozostawia jego natywny picker, który uruchamia się w wybranej, zarejestrowanej lokalizacji. Grupa repozytorium z kilkoma worktree wymaga doprecyzowania lokalizacji. WM nie parsuje prywatnych plików historii Claude. Własne tytuły w tym PoC są dostępne dla rozmów Codexa.

Własne tytuły są zapisywane w `conversation-titles.json` w katalogu stanu WM, pod kluczem provider i identyfikator rozmowy. Zapis jest atomowy i używa istniejącej blokady stanu. Puste pole przywraca oryginalny tytuł. Resume otrzymuje oryginalny identyfikator. Oryginalne pliki i bieżące procesy agentów zachowują niezależny cykl życia.

## Dwie iteracje i walidacja

Pierwsza wersja wprowadziła panel kontekstu i pikery. W drugiej rozróżniono tło nagłówka od treści, zmniejszono ciężar dolnych akcji i zapisano zrzuty z rozwiniętym drzewem. Długie nazwy przy 28 kolumnach ulegają elipsie, a mały terminal przewija dolne akcje w tym samym sidebarze.

| Szerokość | Iteracja 1 | Iteracja 2 | Izolowany tmux |
| --- | --- | --- | --- |
| 28 | [SVG](../../features/premium-sidebar/context-iteration1-28.svg) | [SVG](../../features/premium-sidebar/context-28.svg) | [SVG](../../features/premium-sidebar/context-tmux-28.svg) |
| 36 | [SVG](../../features/premium-sidebar/context-iteration1-36.svg) | [SVG](../../features/premium-sidebar/context-36.svg) | [SVG](../../features/premium-sidebar/context-tmux-36.svg) |
| 50 | [SVG](../../features/premium-sidebar/context-iteration1-50.svg) | [SVG](../../features/premium-sidebar/context-50.svg) | [SVG](../../features/premium-sidebar/context-tmux-50.svg) |

Zrzuty pokazują faktyczny render Textual na kontrolowanych danych i osobno działający tmux z prawdziwą powłoką. Test PTY sprawdza wybór worktree, wejście do obu powłok, zmianę rozmiaru, detach i zachowanie PID oraz zmiennych po reconnect. Testy UI sprawdzają lokalne filtrowanie, wybór terminala w innym workspace, wyszukiwanie, trwałość tytułu i resume z właściwym identyfikatorem, picker Claude we wskazanym katalogu i zamknięcie historii w trakcie ładowania. Nie wymagają zalogowanych agentów.

## Decyzja

**CONDITIONAL GO.** Panel kontekstowy ułatwia powrót do właściwego worktree przy zachowaniu globalnych sesji i istniejącego backendu. Do dalszej walidacji pozostają zalogowane sesje Codex i Claude Code, historia Claude dostępna przez stabilne API, sprawdzenie na Linuksie oraz istniejące ryzyko współbieżnych zewnętrznych klientów tmux. Rozmowy bez pewnej ścieżki powinny pozostać neutralne, a lokalna etykieta nie powinna zmieniać tożsamości rozmowy. [Własność sesji](tmux-session-ownership.md)

Pełny pytest na macOS — 136 testów i 30 podtestów. Sześć testów ukierunkowanych przeszło również po doprecyzowaniu etykiet globalnych sesji. Ruff, mypy i trzy rundy niezależnego review przeszły. Zainstalowany Codex app-server zaakceptował zapytanie bez cwd w odizolowanym katalogu stanu i zwrócił pustą stronę. W działającym sidebarze zweryfikowano widok `bookr / aaaa`, puste stany i zachowanie PID prawej powłoki.
