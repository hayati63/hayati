// ---- driver: load per-TF CSVs (epoch,open,high,low,close,volume), tick at each M5 bar open ----
static void load_tf(ENUM_TIMEFRAMES tf, const char* path) {
  FILE* f = fopen(path, "r"); if (!f) { fprintf(stderr, "cannot open %s\n", path); exit(1); }
  char line[256]; auto& v = EMU_TF()[(int)tf];
  while (fgets(line, sizeof line, f)) { MqlRates r{}; long long t; long vol;
    if (sscanf(line, "%lld,%lf,%lf,%lf,%lf,%ld", &t, &r.open, &r.high, &r.low, &r.close, &vol) == 6) { r.time = t; r.tick_volume = vol; v.push_back(r); } }
  fclose(f);
}
int main(int argc, char** argv) {
  const char* dir = argv[1];
  const char* names[] = {"M5", "M15", "H1", "H4", "D1"};
  ENUM_TIMEFRAMES tfs[] = {PERIOD_M5, PERIOD_M15, PERIOD_H1, PERIOD_H4, PERIOD_D1};
  for (int i = 0; i < 5; i++) { std::string p = std::string(dir) + "/" + names[i] + ".csv"; load_tf(tfs[i], p.c_str()); }
  auto& m5 = EMU_TF()[(int)PERIOD_M5];
  EMU_NOW() = m5[0].time; EMU_BID() = m5[0].open;
  if (OnInit() != INIT_SUCCEEDED) { puts("init failed"); return 1; }
  for (size_t i = 0; i < m5.size(); i++) { EMU_NOW() = m5[i].time; EMU_BID() = m5[i].open; OnTick(); }
  OnDeinit(0);
  return 0;
}
