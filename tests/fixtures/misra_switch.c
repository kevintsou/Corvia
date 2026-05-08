int single_clause(int x) {
    switch (x) {
        case 1:
            return 1;
    }
    return 0;
}

int missing_default(int x) {
    switch (x) {
        case 1: return 1;
        case 2: return 2;
    }
    return 0;
}

int missing_break(int x) {
    int y = 0;
    switch (x) {
        case 1:
            y = 1;
        case 2:
            y = 2;
            break;
        default:
            y = 0;
            break;
    }
    return y;
}

int boolean_switch(int x) {
    int y = 0;
    switch (x == 1) {
        case 0: y = 0; break;
        case 1: y = 1; break;
        default: break;
    }
    return y;
}

int default_in_middle(int x) {
    int y = 0;
    switch (x) {
        case 1: y = 1; break;
        default: y = 99; break;
        case 2: y = 2; break;
    }
    return y;
}

int well_formed(int x) {
    switch (x) {
        case 1: return 1;
        case 2: return 2;
        default: return 0;
    }
}
