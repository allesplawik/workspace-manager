# Wymagania WM 3.0

MVP obejmuje P0 i P1 w zatwierdzonym zakresie. P2 wymaga osobnej decyzji. Aktualny status i dowody są w [macierzy](../roadmap/feature-matrix.md). Identyfikator pozostaje stały po zmianie implementacji.

- **WM-WS-01** (P0) — Utworzenie i ponowne odczytanie workspace.
- **WM-WS-02** (P0) — Bezpieczne wyrejestrowanie workspace.
- **WM-WS-03** (P1) — Wybór i wyszukiwanie workspace/repo/worktree.
- **WM-CFG-01** (P0) — Konfiguracja i rejestr przetrwają restart.
- **WM-WT-01** (P0) — Dodanie i utworzenie worktree dla repozytorium.
- **WM-WT-02** (P1) — Listowanie, wybór i otwieranie katalogu roboczego.
- **WM-WT-03** (P0) — Usunięcie wyłącznie czystego, rozpoznanego worktree.
- **WM-WT-04** (P0) — Ochrona przed usunięciem podczas pracy terminala.
- **WM-WT-05** (P1) — Obsługa zaginionego katalogu i przerwanej operacji.
- **WM-WT-06** (P1) — Jawna zmiana brancha w już dodanym repo z ochroną pracy i aktywnych terminali.
- **WM-SES-01** (P0) — Tworzenie sesji Shell i wybór katalogu.
- **WM-SES-02** (P0) — Uruchomienie obu agentów i wiele sesji w jednym worktree.
- **WM-SES-03** (P0) — Przełączenie właściwego procesu bez utraty PID.
- **WM-SES-04** (P0) — Detach/reconnect przy żywym serwerze.
- **WM-SES-05** (P0) — Zakończenie tylko wybranego własnego panelu po potwierdzeniu.
- **WM-SES-06** (P0) — Diagnoza braku panelu i porażki podłączenia.
- **WM-TAB-01** (P1) — Pasek, aktywacja i zamknięcie karty bez zakończenia.
- **WM-TAB-02** (P1) — Dwukierunkowa synchronizacja karty, terminala i kontekstu.
- **WM-TAB-03** (P1) — Trwałe nazwy sesji i reset do nazwy domyślnej.
- **WM-TAB-04** (P1) — Odtworzenie kart i rozpoznanie zakończonego celu.
- **WM-HIS-01** (P1) — Odczyt historii Codexa, globalny filtr i dokładne cwd.
- **WM-HIS-02** (P1) — Lokalne własne tytuły Codexa.
- **WM-HIS-03** (P0) — Resume z oryginalnym ID oraz ostrzeżenie dla nieprzypisanego kontekstu.
- **WM-HIS-04** (P1) — Katalog historii Claude i własne tytuły w WM.
- **WM-MEM-01** (P1) — Wspólna pamięć workspace, odczyt i zapis z rewizją.
- **WM-MEM-02** (P2) — Osobny kontekst pamięci repo/worktree.
- **WM-UI-01** (P1) — Nawigacja, menu, wybór bez niejawnej zmiany brancha.
- **WM-UI-02** (P0) — Fokus po aktywacji, zoom i resize bez złego routingu.
- **WM-CLI-01** (P0) — Punkty wejścia i zgodność automatyzacji.
- **WM-REL-01** (P0) — Dystrybucja i wydanie na docelowych platformach.
- **WM-MULTI-01** (P1) — Kilka niezależnych repozytoriów w jednym workspace.
- **WM-MULTI-02** (P2) — Trwałe zadanie obejmujące kilka repo/worktrees i sesji.

Niezmienniki. operacje destrukcyjne wymagają potwierdzenia i weryfikacji własności. Rozmowa, proces i zakładka mają osobne tożsamości. UI i CLI egzekwują tę samą politykę. MVP obsługuje kilka repozytoriów w jednym workspace oraz natywny picker Claude. Katalog historii Claude wymaga uzgodnienia stabilnego źródła.
