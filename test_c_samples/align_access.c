/* Test fixture for the align-access external checker.
 *
 * Cases marked BAD must be reported; cases marked GOOD must NOT be reported.
 * The GOOD cases are drawn from real patterns in the Phison secure_boot tree
 * that earlier hand-review confirmed to be correct.
 */

typedef unsigned char  U8;
typedef unsigned short U16;
typedef unsigned int   U32;
typedef unsigned long long U64;

/* ---------- Pattern 1: widening casts ---------- */

U32 bad_u8_array_offset(void)
{
    U8 buf[64];
    /* BAD: buf+1 is provably not 4-byte aligned */
    return *(U32 *)(buf + 1);
}

U32 bad_u8_ptr_widened(U8 *p)
{
    /* BAD: U8* carries no 4-byte alignment guarantee */
    return ((U32 *)p)[2];
}

U32 bad_void_ptr_widened(void *v)
{
    /* BAD: void* carries no alignment guarantee */
    return *(U32 *)v;
}

U64 bad_u16_to_u64(U16 *h)
{
    /* BAD: 2-byte source widened to an 8-byte access */
    return *(U64 *)h;
}

U32 good_same_width_cast(U32 *already_u32)
{
    /* GOOD: redundant same-width cast - real case at
     * dal_sec_sha_api.c:123, ((U32 *)hmac_key)[i] where hmac_key is U32*. */
    return ((U32 *)already_u32)[1];
}

U32 good_u32_array(void)
{
    U32 words[16];
    /* GOOD: naturally aligned U32 array element */
    return words[3];
}

U16 good_narrowing_cast(U32 *w)
{
    /* GOOD: narrowing, never an alignment problem */
    return *(U16 *)w;
}

/* ---------- Pattern 3: constant register offsets ---------- */

void good_aligned_reg_writes(void)
{
    /* GOOD: all offsets are multiples of 4 - real cases from host.c:720-724 */
    *(volatile U32 *)(0x3221000 + 0x7C) = 0xB;
    *(volatile U32 *)(0x03200000 + 3 * 0x8000 + 0x1000 + 0xDD0) = 0x0;
    *(volatile U32 *)0x03600578UL = 0x1;
}

void bad_misaligned_reg_writes(void)
{
    /* BAD: 0x7E % 4 == 2 */
    *(volatile U32 *)(0x03200000 + 0x7E) = 0x1;
    /* BAD: 0x1001 % 4 == 1 */
    *(volatile U32 *)(0x03200000 + 0x1001) = 0x2;
}

/* ---------- Pattern 1b: &element address widened ---------- */

typedef struct {
    U8  *start;
    U32 offset;
} log_buf_t;

U32 bad_local_array_runtime_index(U32 i)
{
    U8 buf[64];
    /* BAD: &buf[i] with a runtime index carries no alignment guarantee */
    return *(U32 *)&buf[i];
}

void bad_struct_member_runtime_index(log_buf_t *log, U32 value)
{
    /* BAD: real pattern from sal_log.c:89 */
    *(U32 *)&log->start[log->offset] = value;
}

U32 good_u32_member_element(U32 *words, U32 i)
{
    /* GOOD: already a U32 element, no widening */
    return *(U32 *)&words[i];
}
