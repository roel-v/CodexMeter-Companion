#pragma once
#include "model.h"

struct TokenDisplayRow {
  uint64_t tokens = 0, cents = 0;
  bool has_tokens = false, has_cost = false, partial = false;
};
// Components 0..2; total 3. Shared semantics, independent of screen geometry.
inline TokenDisplayRow token_display_row(const TokenBreakdown& b, int row,
                                         bool has_total, uint64_t total) {
  TokenDisplayRow result;
  result.partial = b.partial || b.unknown;
  result.has_tokens = row == 3 ? has_total : b.valid;
  result.tokens = row == 3 ? total : b.tokens[row];
  result.has_cost = b.valid;
  if (row != 3) result.cents = b.cents[row];
  else for (auto cents : b.cents) {
    if (UINT64_MAX - result.cents < cents) {
      result.has_cost = false; result.cents = 0; break;
    }
    result.cents += cents;
  }
  return result;
}
