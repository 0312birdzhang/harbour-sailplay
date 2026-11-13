#define _GNU_SOURCE
#include <grp.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>

int main(int argc, char **argv)
{
    if (argc != 2) return 2;
    const int phone = strcmp(argv[1], "phone") == 0;
    if (!phone && strcmp(argv[1], "messages") != 0) return 2;
    const struct group *group = getgrnam("privileged");
    if (!group || getegid() != group->gr_gid || setresgid(group->gr_gid, group->gr_gid, group->gr_gid) != 0) {
        fprintf(stderr, "sailplay: communication launch group is unavailable\n");
        return 1;
    }
    execl("/usr/bin/sailjail", "sailjail", "-p",
        phone ? "sailplay-phone-backend" : "sailplay-messages-backend", "--",
        phone ? "/usr/bin/sailplay-phone-backend" : "/usr/bin/sailplay-messages-backend",
        "--backend", argv[1], (char *)0);
    perror("sailplay: communication sandbox launch failed");
    return 1;
}
