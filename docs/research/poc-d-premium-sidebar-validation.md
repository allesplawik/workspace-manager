# PoC D — Premium Workspace Explorer

## Cel i stan wyjściowy

Eksperyment sprawdza, czy Workspace Explorer oparty na Textual może uzyskać czytelną hierarchię i ergonomię współczesnego eksploratora IDE obok natywnego terminala tmux. Punktem wyjścia był działający PoC D z drzewem workspace → repozytorium → worktree, wyborem istniejących sesji, historią rozmów, Memory oraz zachowaniem procesów po odłączeniu. Jednowierszowa lista sesji ścinała razem nazwę, branch i stan. Na wąskim panelu szerokie obramowanie wyszukiwania i tła sekcji konkurowały z drzewem.

Prace wykonano w dotychczasowym worktree `experiment/integrated-terminal-workspace`, z zachowaniem roboczych zmian wcześniejszych etapów.

## Rozwiązanie

- Centralna paleta inspirowana GitHub Dark i TCSS kształtują nagłówek, jednoliniowe wyszukiwanie, sekcje, fokus oraz wyszarzony footer. Odświeżanie i menu pozostają w istniejącym nagłówku Explorer.
- Istniejący `ExplorerTree` zachowuje nawigację i dane. Rich dodaje ikony poziomów, kolor i priorytety skracania. `◆` oznacza wybrany worktree, `▸` worktree wyświetlanej sesji, a zielona kropka obecność działającego procesu. Fokus ma własne podświetlenie.
- Mały widget `SessionCards` opiera się na publicznym `OptionList`. Każda opcja ma dwie linie Rich. Aktualny terminal ma niebieskie tło i pasek, a fokus klawiatury wyróżnia osobny styl. Identyfikator opcji jest dotychczasowym identyfikatorem panelu, więc kliknięcie, Enter i menu korzystają z tego samego backendu. Stany `open`, `live` i `ended` wynikają z widoku i tmux. Nie wnioskujemy z nich o pracy agenta.
- Conversations i Memory zachowują dotychczasową funkcjonalność. Gęstszy układ dotyczy Explorera. Prawy panel pozostaje natywnym klientem tmux, a punkt wejścia `wm split` jest dostępny.

## Walidacja wizualna i ergonomia

Przejrzano rzeczywiste eksporty SVG ekranu Textual, przy kontrolowanych danych z fixture workspace i sesji. Eksport odtwarza ekran aplikacji. Zrzuty makiety nie były używane. Do sprawdzenia koloru powtórzono eksport bez środowiskowego `NO_COLOR`. Poniżej znajdują się lokalne artefakty z tego samego worktree.

| Kolumny | Przed zmianą | Iteracja 1 | Iteracja 2 | Obserwacja |
| --- | --- | --- | --- | --- |
| 28 | [SVG](../../features/premium-sidebar/baseline-28.svg) | [SVG](../../features/premium-sidebar/iteration1-28.svg) | [SVG](../../features/premium-sidebar/iteration2-28.svg) | Nagłówki i menu mieszczą się. Branch, stan i marker aktywności pozostają czytelne przy skracaniu długich nazw. |
| 36 | [SVG](../../features/premium-sidebar/baseline-36.svg) | [SVG](../../features/premium-sidebar/iteration1-36.svg) | [SVG](../../features/premium-sidebar/iteration2-36.svg) | Standardowy układ mieści typ agenta, repo i branch w osobnych liniach. |
| 50 | [SVG](../../features/premium-sidebar/baseline-50.svg) | [SVG](../../features/premium-sidebar/iteration1-50.svg) | [SVG](../../features/premium-sidebar/iteration2-50.svg) | Dodatkowe miejsce odsłania dłuższe etykiety. Prawy panel nadal przyjmuje wejście. |

Pierwsza iteracja wykazała, że dotychczasowe wcięcia zabierają miejsce na końcowy znacznik działającej sesji. Druga zmniejszyła głębokość prowadnic, nadała znacznikowi priorytet przy elipsie i zarezerwowała miejsca na repo również przy długiej nazwie sesji. Pełne etykiety są dostępne w podpowiedziach i w szczegółach sesji. Podpowiedź myszy odpowiada aktualnie wskazanej karcie, a fokus klawiatury służy jako punkt odniesienia po opuszczeniu listy. Przy wysokości 18 wierszy lista przewija się, a footer zostaje przy dolnej krawędzi. Mechanizm zmiany rozmiaru tmux nadal rezerwuje co najmniej 40 kolumn dla prawego terminala przed przejściem do trybu jednokolumnowego.

Z rzeczywistego izolowanego tmux wyeksportowano także zawartość obu paneli z zachowaniem ANSI. Panel po prawej pokazuje wynik polecenia przyjętego przez PTY. [28 kolumn](../../features/premium-sidebar/tmux-28.svg) · [36 kolumn](../../features/premium-sidebar/tmux-36.svg) · [50 kolumn](../../features/premium-sidebar/tmux-50.svg)

## Walidacja techniczna

Środowisko lokalne — macOS Intel, Python 3.12 i tmux 3.8. Testy uruchomiono z tymczasową konfiguracją i osobnymi socketami.

- Bazowy pytest — 126 testów i 30 podtestów. Końcowy pytest — 127 testów i 30 podtestów, wszystkie przeszły.
- Pilot Textual obejmuje nawigację i rozwijanie, puste sekcje, widoczność akcji przy 28 kolumnach, skracanie długich nazw, zaznaczenie, dwie linie karty, zmianę rozmiaru 28/36/50 przy wysokości 18, przewijanie wielu sesji i stały footer.
- Test prawdziwego tmux i PTY obejmuje zmianę rozmiaru klawiszami do 28, 36 i 50, zmianę myszą, wybór dwóch shelli przez kliknięcie kart, zachowanie PID i stanu, hide/show, detach oraz reconnect.
- `ruff check src tests`, kontrola formatowania zmienionych plików i `mypy src` przeszły. Niezależny przegląd kodu zakończył się bez otwartych uwag.
- Linux, konkretne emulatory terminala i uwierzytelnione sesje Codex/Claude nie zostały ponownie zweryfikowane w tej fazie.

## Wnioski

**CONDITIONAL GO.** Textual odtwarza hierarchię, typografię, kolory i stany znane z eksploratorów IDE. Implementacja używa istniejących widgetów z cienką warstwą prezentacji i nie wymaga nowych zależności ani przebudowy integracji. Przy 28 kolumnach kompromisem jest elipsa. Font, szerokości znaków Unicode i odwzorowanie kolorów zależą od terminala. W układzie znakowym warto utrzymać proste symbole, zwarty rytm oraz odrębne wskazania fokusu i aktywności.

Przed docelowym wdrożeniem pozostaje sprawdzić renderowanie i ergonomię podczas dłuższej pracy na Linuksie i z rzeczywistymi agentami oraz zamknąć wcześniejsze ryzyka współdzielonego klienta tmux i nieudanego podłączenia. [Własność sesji i ograniczenia](tmux-session-ownership.md)
