# Budżet domowy 0.9.4

Aplikacja na Maca do analizy domowego budżetu na podstawie wyciągów bankowych (mBank, ING, MT940, Revolut) i skanów paragonów.
Gotowy instalator: `dist/BudzetDomowy-0.9.4.zip`. Kod źródłowy: `BudzetDomowy.app/Contents/Resources/app`.

## Zrzuty ekranu (dane przykładowe)

![Przegląd](docs/screenshots/1-przeglad.png)
![Paragon](docs/screenshots/5-paragon.png)
![Produkty](docs/screenshots/6-produkty.png)
![Transakcje](docs/screenshots/3-transakcje.png)
![Konta](docs/screenshots/8-konta.png)
![Rozliczenia](docs/screenshots/9-rozliczenia.png)
![Tryb ciemny](docs/screenshots/2-przeglad-ciemny.png)

Instalacja
1. Przeciągnij "BudzetDomowy.app" do folderu Programy.
2. Pierwsze uruchomienie: kliknij program prawym przyciskiem i wybierz "Otwórz"
   (na macOS 15 i nowszych: Ustawienia systemowe > Prywatność i ochrona > "Otwórz mimo to").
   Program nie jest podpisany przez Apple, dlatego system pyta o zgodę.
3. Program otwiera się w przeglądarce pod adresem http://127.0.0.1:8765 i działa tylko na tym komputerze.

Wymagania
- macOS 12 lub nowszy.
- Narzędzia Apple (Command Line Tools): w Terminalu "xcode-select --install".
  Dają Pythona i odczyt tekstu z paragonów. Jeśli masz już Pythona z Homebrew, program go użyje,
  ale narzędzia Apple nadal są potrzebne do odczytu paragonów.

Dane
- Wszystko zapisuje się w ~/Library/Application Support/BudzetDomowy (baza budzet.db i folder paragony).
- Kopia zapasowa = kopia tego folderu.

Zamykanie
- Ustawienia > "Zamknij program". Samo zamknięcie karty przeglądarki zostawia program w tle.
