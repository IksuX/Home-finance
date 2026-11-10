# Budżet domowy 0.1.0

Aplikacja na Maca do analizy domowego budżetu na podstawie wyciągów bankowych (mBank, ING) i skanów paragonów.
Gotowy instalator: `dist/BudzetDomowy-0.1.0.zip`. Kod źródłowy: `BudzetDomowy.app/Contents/Resources/app`.

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
