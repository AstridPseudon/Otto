/* Native entrypoint for the staging-only fake Claude turn.
 *
 * The worker fence admits the pinned launcher and the Python executable used
 * by its sole MCP server. Execute Python explicitly so a script shebang does
 * not have to cross the restricted process-exec boundary implicitly.
 */
#define _XOPEN_SOURCE 700
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#ifndef PERCH_PYTHON
#define PERCH_PYTHON "/opt/homebrew/bin/python3.11"
#endif

int main(int argc, char **argv) {
    if (argc == 2 && strcmp(argv[1], "--version") == 0) {
        puts("2.1.293 (Claude Code)");
        return 0;
    }
    char python[PATH_MAX];
    char script[PATH_MAX];
    int length = snprintf(script, sizeof(script), "%s.py", argv[0]);
    if (realpath(PERCH_PYTHON, python) == NULL ||
        length < 0 || length >= (int)sizeof(script)) {
        perror("PERCH fake Claude launcher path");
        return 127;
    }
    char **command = calloc((size_t)argc + 3, sizeof(char *));
    if (command == NULL) {
        perror("PERCH fake Claude launcher arguments");
        return 127;
    }
    command[0] = python;
    command[1] = "-B";
    command[2] = script;
    for (int index = 1; index < argc; ++index) command[index + 2] = argv[index];
    execv(python, command);
    perror("PERCH fake Claude Python exec");
    return 127;
}
