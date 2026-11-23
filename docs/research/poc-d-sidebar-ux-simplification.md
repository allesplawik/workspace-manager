# PoC D — Minimalist Workspace Explorer

## Punkt wyjścia

Na przesłanym zrzucie nadal działała wcześniejsza wersja sidebaru. Roboczy wariant Premium miał już jednoliniową wyszukiwarkę i dwuwierszowe karty, ale wciąż pokazywał akcje w każdej sekcji oraz instrukcję i zakres historii. Zmiany wprowadzono w tym samym worktree i w istniejących komponentach.

Podpowiedzi po najechaniu należą do Textual. Pasek pod historią i długie ostrzeżenie o równoległych sesjach należą do Workspace Managera. Ostrzeżenie generuje polityka konfliktów backendu, a dotychczasowy interfejs powielał je w komunikacie i powiadomieniu. Ekrany po prawej stronie należą do procesów uruchamianych przez tmux.

## Uproszczenia

- Nagłówek ma jedno menu. Jedynymi dodatkowymi akcjami widocznymi stale są tworzenie workspace'u i tworzenie sesji. Menu zachowuje dostęp do odświeżania, operacji na repozytorium, sesjach i rozmowach. Menu kontekstowe wiersza nadal otwiera się klawiszem F10.
- Wyszukiwanie zajmuje jeden wiersz. Drzewo zachowuje wcięcia i znaczniki rozwijania. Kropka przy worktree wskazuje działającą sesję, a kolor rozróżnia worktree aktualnie podłączonego terminala.
- Sesje zachowują dwie linie. Stan `connected` oznacza terminal wyświetlany po prawej. Pozostałe dostępne stany to `live` i `ended`.
- Conversations i Memory startują zwinięte. Historia pokazuje tytuły i rozróżnia ładowanie, błąd i pustą listę. Szczegóły i resume są dostępne. Memory korzysta z jednej pozycji „Read memory”.
- Ostrzeżenie o równoległych sesjach znika po krótkim powiadomieniu, a pełna treść pozostaje w menu „Last warning”. Blokada startu ma własny krótki komunikat, wpis „Last message” z pełną treścią, który pozostaje dostępny po zwężeniu okna.

## Walidacja

Porównano zrzuty istniejącego renderu Textual przy [28](../../features/premium-sidebar/minimal-28.svg), [36](../../features/premium-sidebar/minimal-36.svg) i [50 kolumnach](../../features/premium-sidebar/minimal-50.svg). Przy 28 kolumnach zmieściły się wszystkie stale widoczne akcje, ale nadal skracane są długie nazwy. Wyeksportowano także dwa rzeczywiste panele izolowanego tmux przy [28](../../features/premium-sidebar/minimal-tmux-28.svg), [36](../../features/premium-sidebar/minimal-tmux-36.svg) i [50 kolumnach](../../features/premium-sidebar/minimal-tmux-50.svg).

Testy Textual obejmują widoczność akcji, zamykanie menu, dostęp do szczegółów ostrzeżenia i blokady, błąd historii oraz zachowanie wyboru po resize. Test tmux potwierdził przełączanie dwóch istniejących powłok z zachowaniem PID i stanu, resize, ukrywanie sidebaru oraz detach i reconnect. W tej iteracji walidację wykonano na macOS Intel. Linux i uwierzytelnione sesje agentów pozostają poza tym pomiarem.

## Podpowiedzi i ograniczenia

Rozwinięte treści kart sesji są dostępne przez Details. Karty sesji i jednowierszowy pasek statusu nie otwierają automatycznych podpowiedzi. Błąd historii zachowuje podpowiedź diagnostyczną. Drzewo pokazuje krótką podpowiedź tylko nad uciętą etykietą. Pomoc jest dostępna w menu i pod klawiszem `?`. Podpowiedzi są widgetami Textual rysowanymi w lewym panelu, gdzie ich miejsce ogranicza rozmiar terminala.

Ostrzeżenie dotyczy wykrytych działających agentów w tym samym workspace. Workspace Manager nie ustala, które pliki agenci rzeczywiście edytują. Reguły istniejącej polityki `warn` i `block` pozostały wspólne z klasycznym trybem.

## Ocena

**CONDITIONAL GO.** Układ usuwa powtarzalne akcje i pozostaje użyteczny przy 28, 36 i 50 kolumnach. Zalecany kierunek to jedno menu, dwie akcje tworzenia oraz krótkie etykiety bez automatycznych podpowiedzi sesji. Dalsze testy powinny objąć dłuższą pracę z zalogowanymi agentami na macOS i Linuksie. Nadal obowiązują wcześniej udokumentowane ograniczenia równoczesnych klientów tmux i nieudanego podłączenia. [Model własności sesji](tmux-session-ownership.md)

Po ostatnich zmianach Ruff i mypy przeszły. Przeszły izolowane testy Textual, niezależne powtórki resize oraz przebieg testu tmux zapisujący trzy zrzuty. Powtórka całego zestawu zatrzymała się na teście PTY po 89 zaliczonych testach. Podczas tego przebiegu komenda wpisana bezpośrednio po kliknięciu karty nie dotarła do powłoki. Powtarzalność przełączenia fokusu po kliknięciu pozostaje otwarta.
