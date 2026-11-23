# Plan przejścia na zintegrowany tryb terminalowy

1. Utrzymywać oba wejścia w worktree PoC D. Porównać tworzenie i usuwanie workspace'ów, dodawanie i usuwanie worktree, status Git, konfigurację, pamięć, historię i resume z trybem klasycznym.
2. Zweryfikować izolację wejścia przy konkurencyjnych klientach tmux. Zachować poprzedni widok i pokazać przyczynę przy nieudanym podłączeniu.
3. Przejść scenariusze manualne dla Codex CLI i Claude Code, w tym przełączanie, resize, mysz, paste, suspend oraz reconnect bez restartu.
4. Uruchomić zestaw regresji na macOS i Linuksie. Sprawdzić terminal lokalny, SSH i uruchomienie z innego tmux.
5. Udostępnić eksperyment po osobnej decyzji. W razie regresji użyć `wm --classic`; trwałe procesy pozostają dostępne przez dotychczasowy backend.

Kryteria akceptacji obejmują zachowanie procesów i ochrony worktree, pełny zestaw operacji z dotychczasowego dashboardu, czytelny widok przy 28 kolumnach oraz przejście testów na obu platformach bez wymagania uwierzytelniania agentów w testach automatycznych.
