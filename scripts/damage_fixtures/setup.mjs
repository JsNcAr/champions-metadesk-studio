// Clone smogon/damage-calc at the pinned commit into .work/ and compile the calc package.
// Usage: npm run setup   (Node 22: ~/.config/nvm/versions/node/v22.22.0/bin)
import {execSync} from "node:child_process";
import {existsSync, readFileSync} from "node:fs";
import {dirname, join} from "node:path";
import {fileURLToPath} from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const commit = readFileSync(join(here, "CALC_COMMIT"), "utf8").trim();
const work = join(here, ".work");
const repo = join(work, "damage-calc");
const run = (cmd, cwd) => execSync(cmd, {cwd, stdio: "inherit"});

if (!existsSync(repo)) {
  run(`mkdir -p ${work}`);
  run(`git clone --filter=blob:none https://github.com/smogon/damage-calc.git ${repo}`);
}
run(`git fetch --depth 1 origin ${commit} && git checkout --quiet ${commit}`, repo);
const calc = join(repo, "calc");
if (!existsSync(join(calc, "node_modules"))) run("npm ci --no-audit --no-fund", calc);
if (!existsSync(join(calc, "dist", "index.js"))) run("npm run compile", calc);
console.log(`damage-calc ${commit} ready at ${calc}`);
