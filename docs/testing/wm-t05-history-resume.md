# WM-T05 — Historia, resume i Workspace Memory

Status **PARTIAL**. Zatwierdzony Release Contract wymaga smoke na zapisanych rozmowach w zalogowanym Codex CLI i Claude Code. Testy automatyczne korzystają z izolowanych danych i kontrolowanych procesów. Nie wykonano uwierzytelnionego smoke.

## Kontrakt i zmiany

- Codex odczytuje metadane przez `app-server` i `thread/list`. Historia kontekstowa wymaga dokładnego dopasowania cwd. Globalna zachowuje wpisy bez przypisania i scala strony według ID. Alias jest metadanym WM, kluczowanym przez agenta i ID. Wyczyszczenie aliasu przywraca źródłowy tytuł.
- Globalne resume ponownie odczytuje rejestr workspace po decyzji użytkownika. Jeśli katalog zniknął albo wpis worktree się zmienił, wyświetla komunikat i nie uruchamia agenta. Dla nieprzypisanej rozmowy użytkownik może jawnie wybrać wskazany kontekst. Domyślny fokus okna potwierdzenia to Cancel. Globalne i lokalne resume przekazują snapshot workspace do launchera. Launcher ponownie sprawdza wpis pod tą samą blokadą tmux co usuwanie worktree.
- Reconnect wybiera istniejący pane tmux, zachowując proces i PID. Resume uruchamia agenta w nowym pane. Codex otrzymuje `resume <oryginalne-ID>`. Claude otrzymuje `--resume` w zweryfikowanym cwd i sam obsługuje wybór rozmowy. Katalog historii Claude pozostaje w 3.1+.
- Na macOS nieudany start app-server przez brak katalogu CODEX_HOME ujawnił błąd sprzątania. Odmowa sygnału dla grupy przesłaniała diagnostykę historii. W tym przypadku WM korzysta z obiektu procesu, by wysłać sygnał liderowi, jeśli jeszcze działa. Standardowe sprzątanie grupy zachowuje TERM i eskalację do KILL.
- Workspace Memory działa per workspace. Istniejące testy potwierdzają trwałość, ochronę rewizji przy współbieżnym zapisie oraz brak zmiany treści po odrzuconym zapisie.

## Dowody akceptacji

| Kryterium | Dowód |
|---|---|
| WM-HIS-01 | `test_global_history_filters_two_pages_without_dropping_unassigned` sprawdza dwa cwd, dwa kursory, wpis bez przypisania i brak duplikatu. |
| WM-HIS-02 | `test_conversation_titles_and_unassigned_history` sprawdza niezależność aliasów i reset, a test PTY otwiera magazyn ponownie i odczytuje zapisany alias. |
| WM-HIS-03 | Test PTY `test_both_providers_real_ptys_reconnect_resize_input_and_resume` kończy poprzedni proces Codexa i sprawdza oryginalne ID oraz cwd nowego procesu mimo aliasu. Test UI sprawdza anulowanie dla brakującego lub nieznanego cwd. |
| Picker WM-HIS-04 | Test PTY sprawdza `--resume`, katalog i zakończenie pickera bez zastępczego terminala. Testy UI odrzucają brakujące i zastąpione worktree. |
| WM-MEM-01 | `test_only_one_concurrent_writer_wins_and_stale_writer_can_merge` oraz `test_cli_json_revision_update_and_stale_write`. |

## Polecenia i smoke wydania

- W odizolowanym środowisku uruchomiono `python -m pytest -q`, `ruff check .`, `ruff format --check .` oraz `mypy src`. Wyniki platform są w [raporcie bazowym](baseline-report.md).
- Lokalnie sprawdzono Codex CLI 0.171.0 i Claude Code 2.1.326 poleceniem `--version`. Rzeczywisty Codex 0.171.0 zwrócił prawidłową pustą stronę przez app-server z nowym, istniejącym katalogiem CODEX_HOME i bez poświadczeń.
- Do smoke użyj autoryzowanego konta i testowego worktree. W Codex zapisz rozmowę z rozpoznawalną treścią, zakończ proces, zmień tytuł w WM i wznów ją z historii. Potwierdź oryginalny wątek, katalog i nowy pane. Sprawdź oddzielnie reconnect do już działającego terminala.
- W Claude uruchom natywny picker ze wskazanego worktree, wybierz wcześniej zapisaną rozmowę i potwierdź treść oraz katalog. W osobnym przebiegu anuluj wybór i porównaj listę zarządzanych terminali sprzed i po operacji.

## Niezależny review

Cztery rundy techniczne. Po pierwszej dodano ponowny odczyt rejestru oraz test wznowienia po zakończeniu starego Codexa. Po drugiej walidację rozszerzono o kontrolę w launcherze pod blokadą i zabezpieczono ścieżkę błędu sygnału. Trzecia runda nie wykazała otwartych uwag blokujących w resume. Wcześniejszy przebieg macOS pod obciążeniem ujawnił niezależny błąd zamykania Textual. Spóźnione podświetlenie zakładki próbowało odczytać odmontowaną tabelę. Czwarta runda potwierdziła obsługę tego przypadku. Pokrewny przypadek spóźnionego zatwierdzenia wyboru pozostaje nieodtworzony.
