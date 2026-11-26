const { exec } = require("child_process");
const express = require("express");
const app = express();
app.get("/run", (req, res) => {
  exec("ls " + req.query.dir);
  res.send(eval(req.query.expr));
});
document.getElementById("x").innerHTML = location.hash;
