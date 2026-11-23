# PoC D — Minimalist Workspace Explorer

## Punkt wyjścia

Na przesłanym zrzucie nadal działała wcześniejsza wersja sidebaru. Roboczy wariant Premium miał już jednoliniową wyszukiwarkę i dwuwierszowe karty, ale wciąż pokazywał akcje w każdej sekcji oraz instrukcję i zakres historii. Zmiany wprowadzono w tym samym worktree i w istniejących komponentach.

Podpowiedzi po najechaniu należą do Textual. Pasek pod historią i długie ostrzeżenie o równoległych sesjach należą do Workspace Managera. Ostrzeżenie generuje polityka konfliktów backendu, a dotychczasowy interfejs powielał je w komunikacie i powiadomieniu. Ekrany po prawej stronie należą do procesów uruchamianych przez tmux.

## Uproszczenia

- Nagłówek ma jedno menu. Jedynymi dodatkowymi akcjami widocznymi stale są tworzenie workspace'u i tworzenie sesji. Menu zachowuje dostęp do odświeżania, operacji na repozytorium, sesjach i rozmowach. Menu kontekstowe wiersza nadal otwiera się klawiszem F10.
- Wyszukiwanie zajmuje jeden wiersz. Drzewo zachowuje wcięcia i znaczniki rozwijania. Kropka przy worktree wskazuje działającą sesję, a kolor rozróżnia worktree aktualnie podłączonego terminala.
- Sesje zachowują dwie linie. Stan `connected` oznacza terminal wyświetlany po prawej. Pozostałe dostępne stany to `live` i `ended`.
- Conversations i Memory startują zwinięte. Historia pokazuje tytuły i rozróżnia ładowanie, błąd i pustą listę. Szczegóły i resume są dostępne. Memory korzysta z jednej pozycji „Read memory”.
- Ostrzeżenie o równoległych sesjach znika po krótkim powiadomieniu, a pełna treść pozostaje w menu „Last warning”. Blokada startu ma własny krótki komunikat, pełną podpowiedź i wpis „Last message”.

## Walidacja

Porównano zrzuty istniejącego renderu Textual przy [28](../../features/premium-sidebar/minimal-28.svg), [36](../../features/premium-sidebar/minimal-36.svg) i [50 kolumnach](../../features/premium-sidebar/minimal-50.svg). Przy 28 kolumnach zmieściły się wszystkie stale widoczne akcje, ale nadal skracane są długie nazwy. Wyeksportowano także dwa rzeczywiste panele izolowanego tmux przy [28](../../features/premium-sidebar/minimal-tmux-28.svg), [36](../../features/premium-sidebar/minimal-tmux-36.svg) i [50 kolumnach](../../features/premium-sidebar/minimal-tmux-50.svg).

Testy Textual obejmują widoczność akcji, zamykanie menu, dostęp do szczegółów ostrzeżenia i blokady, błąd historii oraz zachowanie wyboru po resize. Test tmux potwierdził przełączanie dwóch istniejących powłok z zachowaniem PID i stanu, resize, ukrywanie sidebaru oraz detach i reconnect. W tej iteracji walidację wykonano na macOS Intel. Linux i uwierzytelnione sesje agentów pozostają poza tym pomiarem.

Końcowy pytest — 129 testów i 30 podtestów. Ruff i mypy przeszły. Dwie rundy niezależnego review zakończyły się bez uwag blokujących. Po zwężeniu okna komunikat, który pierwotnie mieścił się w wierszu, może zostać skrócony bez podpowiedzi.
