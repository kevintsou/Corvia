struct BadBitfields {
    char flag : 1;
    long value : 4;
    int single_bit : 1;
};

struct GoodBitfields {
    unsigned int flag : 1;
    unsigned int value : 4;
    unsigned int count : 8;
};
