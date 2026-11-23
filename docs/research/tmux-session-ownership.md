# PoC D — Własność sesji tmux

Sesja procesu pozostaje na dotychczasowym serwerze tmux. Nazwa `wm-<workspace ID>` i opcja `@wm_id` określają przynależność. Klucz widoku łączy ID workspace'u i ID panelu. Oddzielny serwer widoku ma prywatny socket, znacznik właściciela i własne panele dashboardu, shella domowego oraz klienta. Ponowne podłączenie zachowuje PID i bufor procesu.

- **Open / Focus** przełącza klienta widoku na istniejący panel. Sprawdza, czy panel żyje i nadal należy do workspace'u.
- **Detach** usuwa wyłącznie klienta widoku i pokazuje powłokę domową. Odłączenie całego widoku pozostawia otwarty układ.
- **Rename** zapisuje opcjonalną etykietę `@wm_name` w opcjach panelu. Brak etykiety wyświetla rodzaj agenta. Rejestr workspace pozostaje kompatybilny.
- **Terminate** korzysta z istniejącego zamykania po potwierdzeniu. Sprawdza własność i odrzuca zamknięcie okna współdzielonego z inną sesją.
- Ochrona usuwania worktree nadal sprawdza trwałe panele workspace, także po odłączeniu widoku. Nawigacja nie wykonuje operacji zmiany brancha.

Klienci uruchamiani przez WM koordynują dostęp blokadą. Surowy klient tmux może chwilowo zmienić aktywne okno tej samej sesji przed wykryciem zmiany. Unikaj równoległego sterowania tą samą sesją przez tmux spoza WM. W prototypie nieudane podłączenie może przywrócić shell domowy bez zachowania poprzedniego widoku i komunikatu błędu.
