// Budżet domowy – uruchamia program (pythonw z folderu runtime) bez okna konsoli.
#include <windows.h>
#include <wchar.h>
int WINAPI wWinMain(HINSTANCE h, HINSTANCE p, PWSTR c, int n) {
    wchar_t dir[MAX_PATH], py[MAX_PATH + 40], app[MAX_PATH + 40], cmd[3 * MAX_PATH];
    GetModuleFileNameW(NULL, dir, MAX_PATH);
    wchar_t *s = wcsrchr(dir, L'\\'); if (s) *s = 0;
    swprintf(py, MAX_PATH + 40, L"%ls\\runtime\\pythonw.exe", dir);
    swprintf(app, MAX_PATH + 40, L"%ls\\app", dir);
    swprintf(cmd, 3 * MAX_PATH, L"\"%ls\" \"%ls\\launch.py\"", py, app);
    if (GetFileAttributesW(py) == INVALID_FILE_ATTRIBUTES) {
        MessageBoxW(NULL, L"Brakuje folderu \"runtime\" obok programu. Rozpakuj całe archiwum BudzetDomowy i uruchom program z rozpakowanego folderu.", L"Budżet domowy", MB_ICONERROR);
        return 1;
    }
    STARTUPINFOW si = { sizeof(si) }; PROCESS_INFORMATION pi;
    if (!CreateProcessW(py, cmd, NULL, NULL, FALSE, 0, NULL, app, &si, &pi)) {
        MessageBoxW(NULL, L"Nie udało się uruchomić programu.", L"Budżet domowy", MB_ICONERROR);
        return 1;
    }
    CloseHandle(pi.hThread); CloseHandle(pi.hProcess);
    return 0;
}
