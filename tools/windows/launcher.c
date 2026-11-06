#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <wchar.h>

#define PATH_CAPACITY 32768
#ifndef JOURNEY_MODULE
#define JOURNEY_MODULE L"journey_planner"
#endif
#ifndef JOURNEY_TITLE
#define JOURNEY_TITLE L"Journey Folder Planner"
#endif

static WCHAR directory[PATH_CAPACITY];
static WCHAR runtime[PATH_CAPACITY];
static WCHAR command[PATH_CAPACITY + 64];

static int launch_error(void)
{
    MessageBoxW(NULL,
        L"Journey could not open. Extract the entire ZIP to a local folder and try again.",
        JOURNEY_TITLE, MB_OK | MB_ICONERROR);
    return 1;
}

int WINAPI wWinMain(HINSTANCE instance, HINSTANCE previous, PWSTR arguments, int show)
{
    (void)instance;
    (void)previous;
    (void)arguments;
    (void)show;
    DWORD length = GetModuleFileNameW(NULL, directory, PATH_CAPACITY);
    if (length == 0 || length >= PATH_CAPACITY) {
        return launch_error();
    }
    WCHAR *separator = wcsrchr(directory, L'\\');
    if (separator == NULL) {
        return launch_error();
    }
    *separator = L'\0';
    if (swprintf(runtime, PATH_CAPACITY, L"%ls\\runtime\\pythonw.exe", directory) < 0
        || swprintf(command, PATH_CAPACITY + 64, L"\"%ls\" -B -m " JOURNEY_MODULE, runtime) < 0) {
        return launch_error();
    }

    STARTUPINFOW startup = { .cb = sizeof(startup) };
    PROCESS_INFORMATION process = {0};
    if (!CreateProcessW(runtime, command, NULL, NULL, FALSE, 0, NULL, directory, &startup, &process)) {
        return launch_error();
    }
    CloseHandle(process.hThread);
    DWORD code = 1;
    WaitForSingleObject(process.hProcess, INFINITE);
    GetExitCodeProcess(process.hProcess, &code);
    CloseHandle(process.hProcess);
    return code == 0 ? 0 : launch_error();
}
