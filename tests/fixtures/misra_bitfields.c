struct flags_ok {
    unsigned int a : 1;
    unsigned int b : 4;
    _Bool c : 1;
};

struct flags_bad {
    char small : 2;
    long wide : 4;
    int single_signed : 1;
};
