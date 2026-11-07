#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <wincred.h>
#include <sddl.h>
#include <objbase.h>
#include <stdio.h>
#include <wchar.h>

static BOOL token_user(HANDLE token, BYTE *buffer, DWORD capacity)
{
    DWORD used = 0;
    return GetTokenInformation(token, TokenUser, buffer, capacity, &used);
}

int wmain(int argc, wchar_t **argv)
{
    if (argc != 2 || wcslen(argv[1]) != 64) return 2;
    for (int i = 0; i < 64; i++) {
        if (!((argv[1][i] >= L'0' && argv[1][i] <= L'9') ||
              (argv[1][i] >= L'a' && argv[1][i] <= L'f'))) return 2;
    }
    char input[60001];
    size_t length = fread(input, 1, sizeof(input) - 1, stdin);
    if (!length || !feof(stdin)) return 2;
    input[length] = 0;
    WCHAR message[60001];
    if (!MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, input, (int)length + 1, message, 60001)) return 2;
    if (MessageBoxW(NULL, message, L"Journey · Review exact batch", MB_YESNO | MB_ICONQUESTION | MB_DEFBUTTON2) != IDYES) return 3;
    HANDLE self = NULL, verified = NULL;
    BYTE own_user[1024], approval_user[1024];
    if (!OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, &self) || !token_user(self, own_user, sizeof(own_user))) return 4;
    WCHAR username[1024] = {0}, domain[1024] = {0}, password[1024] = {0};
    DWORD auth_package = 0, auth_size = 0;
    PVOID auth = NULL;
    CREDUI_INFOW ui = { .cbSize = sizeof(ui), .hwndParent = NULL,
        .pszCaptionText = L"Journey · Authorize with your current Windows account",
        .pszMessageText = L"Approve the exact batch you just reviewed. Use your account password. Credentials remain in this Windows dialog." };
    DWORD result = CredUIPromptForWindowsCredentialsW(&ui, 0, &auth_package, NULL, 0, &auth, &auth_size, NULL, CREDUIWIN_SECURE_PROMPT);
    BOOL accepted = FALSE;
    if (result == ERROR_SUCCESS) {
        DWORD users = 1024, domains = 1024, passwords = 1024;
        if (CredUnPackAuthenticationBufferW(0, auth, auth_size, username, &users, domain, &domains, password, &passwords)) {
            WCHAR *separator = wcschr(username, L'\\');
            if (separator && !domain[0]) {
                size_t prefix = (size_t)(separator - username);
                if (prefix < 1024) {
                    wmemcpy(domain, username, prefix);
                    domain[prefix] = 0;
                    memmove(username, separator + 1, (wcslen(separator + 1) + 1) * sizeof(WCHAR));
                }
            }
            if (LogonUserW(username, domain[0] ? domain : NULL, password, LOGON32_LOGON_INTERACTIVE, LOGON32_PROVIDER_DEFAULT, &verified)) {
                if (token_user(verified, approval_user, sizeof(approval_user))) {
                    accepted = EqualSid(((TOKEN_USER *)own_user)->User.Sid, ((TOKEN_USER *)approval_user)->User.Sid);
                }
            }
        }
    }
    SecureZeroMemory(password, sizeof(password));
    SecureZeroMemory(username, sizeof(username));
    SecureZeroMemory(domain, sizeof(domain));
    if (auth) { SecureZeroMemory(auth, auth_size); CoTaskMemFree(auth); }
    if (verified) CloseHandle(verified);
    CloseHandle(self);
    if (!accepted) return result == ERROR_CANCELLED ? 3 : 4;
    LPWSTR sid = NULL;
    if (!ConvertSidToStringSidW(((TOKEN_USER *)own_user)->User.Sid, &sid)) return 4;
    wprintf(L"%ls\n%ls\n", argv[1], sid);
    LocalFree(sid);
    return 0;
}
