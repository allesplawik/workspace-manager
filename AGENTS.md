# Zasady pracy nad Workspace Manager

## Obowiązkowy review zmian

- Każda nowa zmiana kodu, testów, konfiguracji lub dokumentacji musi przejść niezależny review przed uznaniem pracy za zakończoną. Dotyczy to również małych poprawek i zmian wprowadzanych po wcześniejszym pozytywnym review.
- Użyj osobnego agenta do review. Reviewer ocenia aktualny diff, istotne miejsca użycia oraz odpowiednie testy; nie edytuje plików, które sam ocenia. Self-review i same testy nie zastępują niezależnego review.
- Jeśli review wykaże błędy, popraw je, wykonaj odpowiednie testy i zleć ponowny niezależny review aktualnego stanu zmian. Powtarzaj ten cykl do braku otwartych ustaleń, maksymalnie przez 5 iteracji review dla danej zmiany.
- Jeśli po 5 iteracjach pozostają błędy, opisz je i zatrzymaj się z oznaczeniem pracy jako nieukończonej. Nie deklaruj PASS ani gotowości do scalenia.
- Zapisuj liczbę iteracji, ustalenia, naprawy i wyniki w lokalnym raporcie review. Raporty i checkpointy trzymaj w pomijanym przez Git katalogu `features/` lub pliku `IMPLEMENTATION_STATUS.md`.
- W odpowiedzi końcowej podaj wynik review, liczbę iteracji, wyniki testów oraz pozostałe ograniczenia. Nie deklaruj niezależnego review, którego faktycznie nie wykonano.
