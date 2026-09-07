"use strict";
const fs = require("node:fs");
const path = require("node:path");
const { Resvg } = require("@resvg/resvg-js");
const directory = path.resolve(__dirname, "../resources");
const source = fs.readFileSync(path.join(directory, "icon.svg"), "utf8");
fs.writeFileSync(path.join(directory, "icon.png"), new Resvg(source).render().asPng());
