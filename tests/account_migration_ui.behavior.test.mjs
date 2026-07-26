import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import vm from "node:vm";

const indexPage = fs.readFileSync(new URL("../index.html", import.meta.url), "utf8");
const legacyPage = fs.readFileSync(new URL("../liff/migrate.html", import.meta.url), "utf8");
const legacyScripts = [...legacyPage.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g)];
const legacyScript = legacyScripts.map((match) => match[1]).find((source) => (
  source.includes("initializeLegacyMigration")
));

function section(page, start, end) {
  const from = page.indexOf(start);
  const to = page.indexOf(end, from);
  assert.notEqual(from, -1, `missing start marker: ${start}`);
  assert.notEqual(to, -1, `missing end marker: ${end}`);
  return page.slice(from, to);
}

function expose(source, names, context = {}) {
  const sandbox = vm.createContext({
    Promise,
    URL,
    URLSearchParams,
    console,
    ...context,
  });
  const exports = names.map((name) => `this.${name} = ${name};`).join("\n");
  new vm.Script(`${source}\n${exports}`).runInContext(sandbox);
  return sandbox;
}

function legacyElements() {
  return {
    migrationStatus: {
      textContent: "",
      dataset: {},
      setAttribute() {},
    },
    startMigrationBtn: {
      disabled: false,
      hidden: false,
      textContent: "開始搬家",
      addEventListener() {},
    },
    openNewLiff: {
      href: "",
      hidden: true,
      textContent: "開啟新版每日平安",
    },
  };
}

test("legacy LIFF initializes the legacy channel and login uses no redirect arguments", async () => {
  assert.ok(legacyScript, "legacy migration behavior script missing");
  assert.match(legacyPage, /static\.line-scdn\.net\/liff\/edge\/2\/sdk\.js/);
  const elements = legacyElements();
  const calls = [];
  const sandbox = expose(
    legacyScript,
    ["initializeLegacyMigration"],
    {
      location: {
        search: "?invite_from=U0123456789abcdef0123456789abcdef&id_token=leak",
      },
      document: {
        getElementById: (id) => elements[id] || null,
      },
      liff: {
        init: async (options) => calls.push(["init", options]),
        isLoggedIn: () => false,
        login: (...args) => calls.push(["login", args]),
      },
    },
  );

  await sandbox.initializeLegacyMigration();

  assert.equal(calls[0][0], "init");
  assert.equal(calls[0][1].liffId, "2010674803-rK98c0lo");
  assert.deepEqual(calls[1], ["login", []]);
  assert.doesNotMatch(elements.migrationStatus.textContent, /U0123|leak/);
});

test("legacy start sends only ID token and builds a provider-safe next URL", async () => {
  assert.ok(legacyScript, "legacy migration behavior script missing");
  const elements = legacyElements();
  const requests = [];
  const oldId = "U0123456789abcdef0123456789abcdef";
  const token = "legacy-secret-id-token";
  const sandbox = expose(
    legacyScript,
    ["startLegacyMigration"],
    {
      location: {
        search: `?open=member&invite_from=${oldId}&id_token=${token}`,
      },
      document: {
        getElementById: (id) => elements[id] || null,
      },
      liff: {
        getIDToken: () => token,
      },
      fetch: async (url, options) => {
        requests.push({url, options});
        return {
          ok: true,
          status: 200,
          json: async () => ({
            ok: true,
            migration_code: "one-time-code",
            expires_in: 600,
          }),
        };
      },
    },
  );

  await sandbox.startLegacyMigration();

  assert.equal(requests.length, 1);
  assert.equal(requests[0].url, "/api/account-migration/start");
  assert.deepEqual(JSON.parse(requests[0].options.body), {});
  assert.equal(
    requests[0].options.headers.Authorization,
    `Bearer ${token}`,
  );
  assert.equal(
    elements.openNewLiff.href,
    "https://liff.line.me/2010848330-UAiqPPYD?migration_code=one-time-code&open=member",
  );
  const publicText = [
    elements.migrationStatus.textContent,
    elements.openNewLiff.textContent,
    elements.openNewLiff.href,
  ].join(" ");
  assert.doesNotMatch(publicText, new RegExp(oldId));
  assert.doesNotMatch(publicText, new RegExp(token));
  assert.doesNotMatch(elements.openNewLiff.href, /invite_from|id_token/);
});

test("legacy submission locks the button and safe failures can retry", async () => {
  assert.ok(legacyScript, "legacy migration behavior script missing");
  const elements = legacyElements();
  let attempts = 0;
  const sandbox = expose(
    legacyScript,
    ["startLegacyMigration"],
    {
      location: {search: "?page=member"},
      document: {
        getElementById: (id) => elements[id] || null,
      },
      liff: {getIDToken: () => "legacy-token"},
      fetch: async () => {
        attempts += 1;
        throw new Error("network U-sensitive raw-code");
      },
    },
  );

  const first = sandbox.startLegacyMigration();
  assert.equal(elements.startMigrationBtn.disabled, true);
  await first;
  assert.equal(elements.startMigrationBtn.disabled, false);
  assert.match(elements.migrationStatus.textContent, /再試一次|稍後/);
  assert.doesNotMatch(elements.migrationStatus.textContent, /U-sensitive|raw-code/);

  await sandbox.startLegacyMigration();
  assert.equal(attempts, 2);
});

test("current LIFF redeems after auth, removes code immediately, and refreshes member data", async () => {
  const migrationSource = section(
    indexPage,
    "let pendingAccountMigrationCode",
    "function requestedAppAction()",
  );
  const elements = {
    accountMigrationCard: {hidden: true, dataset: {}},
    accountMigrationTitle: {textContent: ""},
    accountMigrationMessage: {textContent: ""},
    accountMigrationSummary: {innerHTML: ""},
    retryAccountMigrationBtn: {hidden: true, onclick: null},
    accountMigrationAction: {hidden: true, href: "", textContent: ""},
  };
  const events = [];
  let resolveFetch;
  const fetchPromise = new Promise((resolve) => {
    resolveFetch = resolve;
  });
  const sandbox = expose(
    migrationSource,
    ["redeemPendingAccountMigration"],
    {
      getAppParam: (key) => key === "migration_code" ? "single-use-code" : "",
      liff: {getIDToken: () => "current-id-token"},
      fetch: (url, options) => {
        events.push(["fetch", url, options]);
        return fetchPromise;
      },
      history: {
        replaceState: (...args) => events.push(["replace", ...args]),
      },
      location: {
        href: "https://example.test/?migration_code=single-use-code&open=member",
        pathname: "/",
        search: "?migration_code=single-use-code&open=member",
        hash: "",
      },
      window: {
        location: {
          href: "https://example.test/?migration_code=single-use-code&open=member",
        },
      },
      document: {
        getElementById: (id) => elements[id] || null,
      },
      loadInitialMemberData: async () => {
        events.push(["loadInitialMemberData"]);
        return {
          status: {ok: true, plan: "paid_399"},
          contacts: [],
          onboarding: {},
        };
      },
    },
  );

  const resultPromise = sandbox.redeemPendingAccountMigration();
  assert.equal(events[0][0], "fetch");
  assert.equal(events[1][0], "replace");
  assert.deepEqual(
    JSON.parse(events[0][2].body),
    {migration_code: "single-use-code"},
  );
  assert.equal(
    events[0][2].headers.Authorization,
    "Bearer current-id-token",
  );
  assert.doesNotMatch(events[1].join(" "), /single-use-code/);

  resolveFetch({
    ok: true,
    status: 200,
    json: async () => ({
      ok: true,
      status: "migrated",
      counts: {
        checkins: 21,
        contacts: 3,
        groups: 1,
        reminders: 2,
        orders: 8,
        requests: 5,
      },
    }),
  });
  const result = await resultPromise;

  assert.equal(result.attempted, true);
  assert.equal(result.succeeded, true);
  assert.equal(events.filter(([name]) => name === "loadInitialMemberData").length, 1);
  assert.equal(elements.accountMigrationCard.hidden, false);
  assert.match(elements.accountMigrationSummary.innerHTML, /21/);
  assert.match(elements.accountMigrationSummary.innerHTML, /3/);
  assert.match(elements.accountMigrationSummary.innerHTML, /1/);
  assert.match(elements.accountMigrationSummary.innerHTML, /2/);
  assert.match(elements.accountMigrationSummary.innerHTML, /進階版/);
  assert.doesNotMatch(elements.accountMigrationSummary.innerHTML, /orders|requests|8|5/);
  assert.equal(indexPage.includes("location.reload()"), false);
});

test("current migration errors show safe recovery and normal fast route stays untouched", async () => {
  const migrationSource = section(
    indexPage,
    "let pendingAccountMigrationCode",
    "function requestedAppAction()",
  );
  const elements = {
    accountMigrationCard: {hidden: true, dataset: {}},
    accountMigrationTitle: {textContent: ""},
    accountMigrationMessage: {textContent: ""},
    accountMigrationSummary: {innerHTML: ""},
    retryAccountMigrationBtn: {hidden: true, onclick: null},
    accountMigrationAction: {hidden: true, href: "", textContent: ""},
  };
  let paramValue = "";
  let fetches = 0;
  let tokenReads = 0;
  const sandbox = expose(
    migrationSource,
    ["redeemPendingAccountMigration"],
    {
      getAppParam: () => paramValue,
      liff: {
        getIDToken: () => {
          tokenReads += 1;
          return "current-token";
        },
      },
      fetch: async () => {
        fetches += 1;
        return {
          ok: false,
          status: 410,
          json: async () => ({ok: false, error: "expired_code"}),
        };
      },
      history: {replaceState() {}},
      location: {href: "https://example.test/", pathname: "/", search: "", hash: ""},
      window: {location: {href: "https://example.test/"}},
      document: {getElementById: (id) => elements[id] || null},
      loadInitialMemberData: async () => {
        throw new Error("must not load on failure");
      },
    },
  );

  const normal = await sandbox.redeemPendingAccountMigration();
  assert.deepEqual(
    {attempted: normal.attempted, succeeded: normal.succeeded},
    {attempted: false, succeeded: false},
  );
  assert.equal(fetches, 0);
  assert.equal(tokenReads, 0);

  paramValue = "expired-code";
  const expired = await sandbox.redeemPendingAccountMigration();
  assert.equal(expired.attempted, true);
  assert.equal(expired.succeeded, false);
  assert.match(elements.accountMigrationMessage.textContent, /超過|過期/);
  assert.match(elements.accountMigrationAction.textContent, /重新|舊版/);
  const publicText = [
    elements.accountMigrationTitle.textContent,
    elements.accountMigrationMessage.textContent,
    elements.accountMigrationSummary.innerHTML,
  ].join(" ");
  assert.doesNotMatch(publicText, /expired-code|current-token|U[0-9a-f]{32}/i);
});

test("used migration code keeps recovery inside the current LIFF", async () => {
  const migrationSource = section(
    indexPage,
    "let pendingAccountMigrationCode",
    "function requestedAppAction()",
  );
  const elements = {
    accountMigrationCard: {hidden: true, dataset: {}},
    accountMigrationTitle: {textContent: ""},
    accountMigrationMessage: {textContent: ""},
    accountMigrationSummary: {innerHTML: ""},
    retryAccountMigrationBtn: {hidden: true, onclick: null},
    accountMigrationAction: {hidden: true, href: "", textContent: ""},
  };
  const sandbox = expose(
    migrationSource,
    ["redeemPendingAccountMigration"],
    {
      getAppParam: () => "used-code",
      liff: {getIDToken: () => "current-token"},
      fetch: async () => ({
        ok: false,
        status: 409,
        json: async () => ({ok: false, error: "used_code"}),
      }),
      history: {replaceState() {}},
      location: {pathname: "/", search: "", hash: ""},
      window: {location: {href: "https://example.test/"}},
      document: {getElementById: (id) => elements[id] || null},
      loadInitialMemberData: async () => ({status: {}, contacts: [], onboarding: {}}),
    },
  );

  await sandbox.redeemPendingAccountMigration();

  assert.match(elements.accountMigrationAction.href, /2010848330-UAiqPPYD/);
  assert.match(elements.accountMigrationAction.href, /open=member/);
  assert.doesNotMatch(elements.accountMigrationAction.href, /2010674803-rK98c0lo/);
  assert.match(elements.accountMigrationAction.textContent, /新版|會員/);
});

test("bootstrap redeems migration before applying a redirecting destination", async () => {
  const bootstrapSource = section(
    indexPage,
    "async function bootstrapApp()",
    "appBootstrapPromise = bootstrapApp()",
  );
  const events = [];
  const sandbox = expose(bootstrapSource, ["bootstrapApp"], {
    appBootstrapComplete: false,
    memberBootstrapState: {},
    setMemberInteractionLocked() {},
    bindTabEvents() {},
    bindSosFab() {},
    bindMvpHome() {},
    bindGuardianCompletePrompt() {},
    bindGuardianEvents() {},
    getAppParam: (key) => key === "migration_code" ? "single-use-code" : (
      key === "open" ? "plans" : ""
    ),
    applyInitialDeepLinkRoute: () => {
      events.push("route");
      return {handled: true, redirected: true};
    },
    lineUserId: "",
    initLine: async () => {
      events.push("auth");
      sandbox.lineUserId = "U-current";
      return true;
    },
    useLocalMode: false,
    redeemPendingAccountMigration: async () => {
      events.push("redeem");
      return {attempted: true, succeeded: true, initialData: {}};
    },
    initApp: async () => {
      events.push("member");
      return true;
    },
    showLineLoginRequired() {},
    document: {body: {removeAttribute() {}, dataset: {}}},
    console: {warn() {}},
  });

  await sandbox.bootstrapApp();

  assert.deepEqual(events, ["auth", "redeem", "member", "route"]);
});

test("migration status card is outside route-hidden application sections", () => {
  const card = indexPage.indexOf('id="accountMigrationCard"');
  const firstAppSection = indexPage.indexOf("<section", indexPage.indexOf('<main class="app">'));
  assert.notEqual(card, -1);
  assert.ok(card < firstAppSection, "migration card must remain visible while routes hide sections");
});
