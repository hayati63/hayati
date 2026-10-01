// ---- driver: M5 bars walked along open -> extreme -> extreme -> close, OnTick at every price ----
static void load_tf(ENUM_TIMEFRAMES tf, const char* path) {
  FILE* f = fopen(path, "r"); if (!f) { fprintf(stderr, "cannot open %s\n", path); exit(1); }
  char line[256]; auto& v = EMU_TF()[(int)tf];
  while (fgets(line, sizeof line, f)) { MqlRates r{}; long long t; long vol;
    if (sscanf(line, "%lld,%lf,%lf,%lf,%lf,%ld", &t, &r.open, &r.high, &r.low, &r.close, &vol) == 6) { r.time = t; r.tick_volume = vol; v.push_back(r); } }
  fclose(f);
}
int main(int argc, char** argv) {
  const char* dir = argv[1];
  const char* names[] = {"M5", "M15", "H1"};
  ENUM_TIMEFRAMES tfs[] = {PERIOD_M5, PERIOD_M15, PERIOD_H1};
  for (int i = 0; i < 3; i++) { std::string p = std::string(dir) + "/" + names[i] + ".csv"; load_tf(tfs[i], p.c_str()); }
  auto& m5 = EMU_TF()[(int)PERIOD_M5];
  EMU_NOW() = m5[0].time; EMU_BID() = m5[0].open;
  if (OnInit() != INIT_SUCCEEDED) { puts("init failed"); return 1; }
  for (size_t i = 0; i < m5.size(); i++) {
    const MqlRates& b = m5[i];
    EMU_SPREAD() = std::max(0.20, std::round(b.open * 1e-4 * 100.0) / 100.0);
    bool bull = b.close >= b.open;
    double path[4] = {b.open, bull ? b.low : b.high, bull ? b.high : b.low, b.close};
    int secs[4] = {0, 60, 180, 299};
    for (int p = 0; p < 4; p++) {
      EMU_NOW() = b.time + secs[p]; EMU_BID() = path[p];
      EMU_PROCESS(p == 0);
      OnTick();
      EMU_PROCESS(false);   // orders sent at this price
    }
  }
  OnDeinit(0);
  FILE* f = fopen(argv[2], "w");
  fprintf(f, "deal,pos,magic,entry,dir,time,price,vol,profit,commission,sl\n");
  for (auto& d : EMU_DEALS()) fprintf(f, "%lu,%lu,%ld,%d,%d,%lld,%.2f,%.2f,%.2f,%.2f,%.2f\n", (unsigned long)d.ticket, (unsigned long)d.pos, d.magic, d.entry, d.dir, d.time, d.price, d.vol, d.profit, d.commission, d.sl);
  fclose(f);
  return 0;
}
