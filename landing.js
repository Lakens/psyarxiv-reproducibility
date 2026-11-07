// Fills the tally from data/tally.json, which the scheduled run writes.
fetch("data/tally.json")
  .then(function (r) { return r.json(); })
  .then(function (t) {
    document.getElementById("tally-preprints").textContent = t.preprints.toLocaleString("en");
    document.getElementById("tally-reports").textContent = t.reports.toLocaleString("en");
    document.getElementById("tally-updated").textContent = t.updated;
  })
  .catch(function () {
    document.getElementById("tally-preprints").textContent = "not yet";
    document.getElementById("tally-reports").textContent = "not yet";
    document.getElementById("tally-updated").textContent = "not yet";
  });
