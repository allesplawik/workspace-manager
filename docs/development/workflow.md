# Workflow kolejnych sesji

1. Sprawdź stan Git, aktywny worktree, `AGENTS.md` i lokalny checkpoint w ignorowanym `features/`. Wskaż bazę i istotne bieżące zmiany. Pierwszy audyt obejmował zastany, niezacommitowany PoC D.
2. Przeczytaj [architekturę](../architecture/current-state.md), [wymagania](../requirements/features.md), [roadmapę](../roadmap/implementation-plan.md) oraz [Release Contract](../release/3.0.0-release-contract.md). Wybierz jedno zatwierdzone zadanie z ukończonymi zależnościami. Zapisz jego ID, granice i plan dowodów.
3. Zmapuj Feature ID → symbol/plik → test → wynik. Sprawdź [kryteria](../requirements/acceptance-criteria.md). Wykonaj istotny baseline przed zmianą. Testy integracyjne uruchamiaj w izolacji według [strategii](../testing/test-strategy.md).
4. Wykonaj najmniejszą zmianę spełniającą kontrakt. Zapisuj rzeczywiste polecenia, wersje narzędzi i stan zasobów. Nie zaliczaj testu tylko na podstawie istnienia funkcji lub testu.
5. Przekaż aktualny diff do niezależnego review według `AGENTS.md`. Zapisz lokalny checkpoint z ustaleniami, naprawami, wynikami i następną dozwoloną czynnością.
6. Zaktualizuj macierz po nowych dowodach, roadmapę po decyzji o zadaniu, architekturę po zmianie granic i strategię po zmianie warunków testu. Zostaw czytelny handoff oparty na dokumentach repozytorium.

## Kontrola zakresu wydania

Sprawdź status akceptacji i freeze w [Release Contract 3.0.0](../release/3.0.0-release-contract.md) przed wyborem zadania. Podaj w checkpointcie, które zatwierdzone kryterium uzasadnia pracę. Zgłoszenia poza zakresem zapisuj jako propozycje 3.1+. Gdy zakres lub platforma wymaga zmiany, zaczekaj na decyzję właściciela. Po freeze stosuj Release Stabilization z kontraktu. Przed zmianą kodu zapisz reprodukcję, naruszone kryterium i powód dopuszczenia poprawki. Czynności wydawnicze prowadź w WM-T07. Przy `Release Ready` zastosuj regułę STOP i przygotuj dowody do akceptacji publikacji. Samo domknięcie review lub testów nie upoważnia do publikacji.

## Źródło prawdy

- [Wymagania](../requirements/features.md) i [kryteria](../requirements/acceptance-criteria.md) definiują oczekiwane zachowanie.
- [Macierz](../roadmap/feature-matrix.md) jest bieżącą oceną i indeksem dowodów.
- [Roadmapa](../roadmap/implementation-plan.md) zawiera zależności oraz decyzje o zakresie.
- [Baseline](../testing/baseline-report.md) jest migawką konkretnego uruchomienia. Kolejne wyniki zapisuj z identyfikacją kodu, środowiska i daty.
- Raporty PoC są historycznym źródłem decyzji. Checkpoint lokalny uzupełnia trwałe dokumenty i może zawierać tymczasowe ścieżki do logów.

## Definition of Done

- Wymaganie i kryteria mają identyfikator. Implementacja pokrywa normalne wejście i istotne błędy.
- Odpowiednie testy zostały uruchomione, a wynik jest zapisany wraz z ograniczeniami. Znane krytyczne regresje blokują DONE.
- Zachowanie weryfikuje niezależny review. Dokumentacja użytkownika i techniczna jest aktualna.
- Status zadania i funkcji został uaktualniony. Blokery i wymagania bez dowodu pozostają jawne.
