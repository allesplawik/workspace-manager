# WM-T07 — Workspace Manager 3.0.0rc1

**Status WM-T07: PARTIAL. Release Ready: BLOCKED.**

## Feature Freeze i artefakty

Rewizja kodu `20398fb848c5dcf33770a7f9aa9f19d7e6a57378` wyznacza Feature Freeze. Źródła RC wyeksportowano poleceniem `git archive 20398fb`. Jedyna zmiana w eksporcie przed budową to numer pakietu w `pyproject.toml`, z `3.0.0.dev0` na `3.0.0rc1`. Polecenie `python -m build --outdir <dist> <snapshot>` z Hatchling 1.33.0 zbudowało sdist i następnie wheel z tego sdist.

| Plik | SHA‑256 |
|---|---|
| `workspace_manager-3.0.0rc1-py3-none-any.whl` | `337c7463ef43262c88def8a903f47d22ed2fae95c7a5655e99d3781d638ae9e4` |
| `workspace_manager-3.0.0rc1.tar.gz` | `7b5f470d1aacc9aa86966f29e4dd9714f547ebf6058d2a5b09fca4ea338f8af9` |

Wheel 2.0.0 użyty w migracji ma SHA‑256 `86e8a50b9862b422aecac6bd54537cf1d50a0c482f5110ffe79dba40532e8b76`.

Lokalny pakiet dowodów jest w `features/production-readiness/3.0.0rc1/`. Obejmuje artefakty, `SHA256SUMS`, skrypty smoke i wheel starszej wersji z rewizji `5aec2c0`. W tej walidacji Python importował zainstalowany wheel w skryptach smoke i migracji. Pełna regresja korzystała z tego samego snapshotu źródeł.

## Środowiska i wyniki

| Środowisko | Instalacja, CLI i launchery w PTY | Migracja i powrót na fixture | Pełna regresja |
|---|---|---|---|
| macOS Intel 15.8.3, Python 3.12.9, Git 2.50.1, tmux 3.8 | PASS | PASS | 180 testów i 35 subtestów PASS |
| Ubuntu 24.04 Docker x86_64, Python 3.12.3, Git 2.43.0, tmux 3.4 | PASS | PASS | 180 testów i 35 subtestów PASS |
| Natywne Ubuntu 24.04 | NOT TESTED | NOT TESTED | NOT TESTED |

Skrypty używają prywatnego HOME, XDG i tmux. Terminal testowy to PTY z `TERM=xterm-256color`. Osobny test w natywnym emulatorze pozostaje NOT TESTED na obu platformach. Sprawdzono TCSS, punkt wejścia, helper `wmcd` w Bash/Zsh, formaty JSON i TSV, kody błędu i wszystkie trzy launchery. Wykonano `ruff check .`, `ruff format --check .`, `mypy src` oraz `python -m pytest -q` w snapshotach testowych. Ruff, format i mypy zakończyły się sukcesem na obu platformach. Pełny pytest trwał 362,38 s na macOS i 239,71 s w Dockerze. Autoryzowane przebiegi na rzeczywistych rozmowach są odłożone. Lokalnie odczytano wersje Codex CLI 0.171.0 i Claude Code 2.1.326.

### Odtworzenie smoke i migracji

W katalogu lokalnych artefaktów zainstaluj każdy wheel w osobnym venv i wskaż oba punkty wejścia. Przebiegi testowe tworzą własny fixture 2.0.0 i odtwarzają kopię tego fixture w tych samych ścieżkach.

```sh
shasum -a 256 -c SHA256SUMS
python3.12 -m venv rc-venv
python3.12 -m venv old-venv
rc-venv/bin/python -m pip install ./workspace_manager-3.0.0rc1-py3-none-any.whl
old-venv/bin/python -m pip install ./workspace_manager-2.0.0-py3-none-any.whl
rc-venv/bin/python smoke.py
rc-venv/bin/python migration.py old-venv/bin/wm rc-venv/bin/wm
```

Migracja wykryła działający legacy Shell, jawnie zarejestrowała jego backend, zachowała klasyfikację `managed` i odmówiła usunięcia aktywnego worktree. Przy powrocie porównano bajty skopiowanych metadanych, ID, HEAD dwóch niezależnych repozytoriów, zawartość plików i PID/cwd tego samego Shella. Instrukcja dla użytkownika jest w [projekcie informacji o wydaniu](../release/3.0.0-release-notes.md).

## Ślad kryteriów

| Scenariusz i wymagania | Dowody i pozostała walidacja |
|---|---|
| E2E-001, WM-WS-01–03, WM-CFG-01, WM-MULTI-01 | Instalowany CLI, fixture migracji z dwoma repo, `test_second_repo_independent_branch` i `test_delete_requires_confirmation_and_preserves_files`. |
| E2E-002, WM-WT-01–06 | Fixture aktywnego worktree blokuje usunięcie. `test_switch_branch_preserves_files_and_other_worktrees`, `test_dirty_remove_blocked_and_clean_branch_retained` i testy odzyskania obejmują Git oraz trwałe metadane. |
| E2E-003/004, WM-SES-01–05 | `test_default_wm_shows_home_and_preserves_workspace_processes`, `test_owned_managed_external_and_replaced_panels` i fixture migracji weryfikują PID, odłączenie, powrót i bezpieczne zakończenie. Smoke rzeczywistych agentów pozostaje otwarty. |
| E2E-005/006, WM-TAB-01/02/04, WM-UI-01/02 | `test_default_wm_shows_home_and_preserves_workspace_processes` i `test_switching_displayed_tab_syncs_context_and_keeps_selection_independent` weryfikują selekcję, fokus, PTY i rozmiary. |
| E2E-007, WM-HIS-01–04, WM-MEM-01 | Testy historii Codexa, `test_both_providers_real_ptys_reconnect_resize_input_and_resume`, testy pamięci i ochrony rewizji. Resume rzeczywistych rozmów obu agentów NOT TESTED. |
| E2E-008, WM-TAB-03/04 | `test_split_collision_preserves_card_and_processes_across_sidebar_restart` obejmuje dwa takie same tytuły, restart, reset nazwy i weryfikację tożsamości. |
| E2E-009, WM-WT-05, WM-SES-06, WM-TAB-04 | Testy awarii attach i wymuszonego rozłączenia w `tests/test_integrated_display.py`, test utraty prywatnego serwera widoku oraz test zakończenia ostatniego backendu. |
| WM-CLI-01, WM-REL-01 | Instalacja RC i migracja fixture przeszły w dwóch dostępnych środowiskach. Natywna walidacja Ubuntu, smoke w emulatorze macOS i ręczne próby z rzeczywistymi agentami pozostają bramkami wydania. |

Dowody automatyczne obejmują wskazane zachowania. Pełny status akceptacji na platformach wydania pozostaje otwarty. Weryfikację ręczną agentów przeprowadź według [WM-T05](wm-t05-history-resume.md) i [kontraktu wydania](../release/3.0.0-release-contract.md). Nie ma decyzji Release Ready ani zatwierdzenia publikacji.

## Niezależny review

Porównanie sdist z archiwum Git potwierdziło zmianę wyłącznie numeru wersji. Zweryfikowano sumy, próbę powrotu do 2.0.0 i rozróżnienie środowisk.

## Regresja wykryta w ręcznej próbie RC1

- WM-SES-01 i WM-UI-01. W Ubuntu 24.04 Docker użytkownik zaliczył tworzenie sesji, przełączanie i Terminate. Na macOS i Ubuntu zauważył jednak opóźnienie pojawienia się karty po udanym starcie w tym samym kontekście.
- Reprodukcja automatyczna. W `test_terminal_opening_message_clears_after_launch_result` launcher zwraca działający nowy panel, a kontrolowane zapytanie o listę już go widzi. Bez cyklicznego odświeżenia sidebar zachowywał dwie poprzednie karty i nie renderował nowej.
- Poprawka w źródłach inicjuje odświeżenie po udanym starcie lub resume w split. RC1 zachowuje opisaną regresję. Przed akceptacją trzeba zbudować nowego kandydata z poprawką i zebrać dowody dla jego artefaktu.

## Następny kandydat — 3.0.0rc2

RC2 jest aktualnym kandydatem. Zbudowano go z archiwum rewizji `ba14105065f0e402f1ff6cc4cb42cd7d309c54a4` jako wheel z sdist. Jedyną zmianą w plikach kodu względem tego archiwum jest numer pakietu `3.0.0rc2`. Rewizja zawiera udokumentowaną poprawkę po Feature Freeze. Ręczne wyniki RC1 są dowodem dla RC1.

| Plik RC2 | SHA‑256 |
|---|---|
| `workspace_manager-3.0.0rc2-py3-none-any.whl` | `c3dd87a55fb3e29b160cdf7867f8bacca6425d559cc2d43d1fbbdd2ed914054d` |
| `workspace_manager-3.0.0rc2.tar.gz` | `768d48b4e9061f3ae36f5181dc1c5d653fa7c200c0560fa3f309e478278b9b58` |

Artefakty, sumy i skrypty są w `features/production-readiness/3.0.0rc2/`. Testowy kontener `wm-ubuntu-rc2` ma nowy stan runtime i jest oddzielony od `wm-ubuntu-rc1`. Wchodzi się do niego poleceniem `docker exec -it wm-ubuntu-rc2 bash`. Test odświeżania używa workspace `rc-test` i worktree `fixture`. Oczekiwany wynik to pojawienie się nowej sesji po udanym starcie bez ręcznego odświeżania.

Walidacja na natywnym Ubuntu, w tym próby agentów, pozostaje otwarta. Status `Release Ready` pozostaje zablokowany.

| Środowisko RC2 | Smoke z wheel | Aktualizacja i odtworzenie 2.0.0 | Regresja źródeł |
|---|---|---|---|
| macOS Intel, tmux 3.8 | PASS | PASS | 180 testów i 35 subtestów PASS. Ruff, format i mypy PASS |
| Ubuntu 24.04 Docker, tmux 3.4 | PASS | PASS | 180 testów i 35 subtestów PASS. Ruff, format i mypy PASS |
| Natywne Ubuntu 24.04 | NOT TESTED | NOT TESTED | NOT TESTED |

Smoke sprawdził `wm`, `wm --classic` i `wm split` w PTY, formaty CLI i `wmcd` w Bash i Zsh. Migracja i powrót zachowały identyfikatory, konfigurację, HEAD dwóch repozytoriów oraz PID i cwd działającego shella. Niezależny review zweryfikował pochodzenie sdist, sumy i izolację kontenerów.

Ręczna próba w Ubuntu 24.04 w kontenerze RC2: **PASS**. Użytkownik potwierdził, że nowa sesja pojawiła się od razu na liście Sessions, bez ręcznego odświeżania.

Otwarte bramki i próby ręczne RC2 są zebrane w [checkliście wydania](../release/3.0.0-release-checklist.md).

Sprawdzenie konsolidacji na źródłach RC2 w macOS Intel: routing launcherów i dwa przypadki powrotu po wyjściu z shella dały 3 testy i 5 subtestów PASS. Dodatkowa próba z zainstalowanym wheel RC2 na dwóch testowych repozytoriach potwierdziła zmianę brancha, usuwanie czystych worktrees z zachowaniem branchy oraz wyrejestrowanie z zachowaniem katalogu. Próba korzystała z osobnego backendu tmux i powłoki w `rc-anchor`.

### RC2 w natywnym Terminal.app na macOS Intel

- **PASS:** zainstalowany wheel uruchomił `wm`, `wm split` i `wm --classic` w Terminal.app 2.14. Potwierdzono klientów rzeczywistego emulatora dla obu wejść split i render klasycznego dashboardu w osobnym oknie.
- **PASS:** dwie sesje Bash w osobnych worktrees fixture. W rzeczywistym widoku A → B → A i aktywacja zakładki zachowały PID, cwd i zmienną środowiskową. Odłączenie prawego widoku oraz odłączenie całego klienta i powrót przez `wm split` zachowały tę samą sesję. Zmiana szerokości okna i sidebar 28/36/50 kolumn przeszły. Zamknięcie ostatniej karty zachowało proces. Zakończenie A pozostawiło działający B. Po zakończeniu B sidebar pokazał `No sessions`.
- Akcje sesji i kart wywołano przez API RC2 i polecenia tmux w odizolowanym fixture. Ten przebieg potwierdza natywny renderer i działanie kontrolera. Poprzedni przebieg automatyczny PTY pokrywa zdarzenia wejściowe i routing.
- **PASS (próba użytkownika):** na macOS Intel zadziałały skróty `Ctrl+B`, potem `f`, `z`, `←` lub `→`. Kliknięcie worktree zmieniło kontekst przy zachowaniu terminala, kliknięcie zakładki przełączyło sesję, a otwarcie i zamknięcie menu `⋯` zachowało aktywną sesję.
- **PASS (zgłoszenie użytkownika):** użytkownik potwierdził działanie opisanych prób Codex CLI i Claude Code na macOS Intel. Brak dostępnego natywnego hosta Ubuntu lub skonfigurowanej VM Ubuntu w lokalnym VirtualBox. Status `RELEASE READY` pozostaje zablokowany.

### Ręczne smoke agentów RC2 w Ubuntu 24.04 w Dockerze

Użytkownik zgłosił **PASS** dla prób Codex CLI i Claude Code wykonanych w kontenerze `wm-ubuntu-rc2`. Scenariusze obejmowały powrót do żywej sesji i wznowienie zapisanej rozmowy we właściwym worktree oraz anulowanie natywnego pickera Claude. Wynik dotyczy Dockera. Próby agentów na natywnym Ubuntu pozostają otwarte. Wynik zgłoszony dla macOS Intel jest w sekcji wyżej.
