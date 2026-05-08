int hex_ok = 0x10;
int dec_ok = 12;
int octal_bad = 010;

unsigned long bad_lower_l = 100l;
unsigned long ok_upper_l = 100L;

void uses_strings(void) {
    char *plain = "hello";
    const char *good = "world";
    (void)plain; (void)good;
}
