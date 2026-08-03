import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import vm from "node:vm";

const page = fs.readFileSync(new URL("../index.html", import.meta.url), "utf8");
const migrationPage = fs.readFileSync(new URL("../liff/migrate.html", import.meta.url), "utf8");
const migrationScript = migrationPage.match(/<script>([\s\S]*?)<\/script>/)?.[1];

function section(start, end) {
  const from = page.indexOf(start);
  const to = page.indexOf(end, from);
  assert.notEqual(from, -1, `missing start marker: ${start}`);
  assert.notEqual(to, -1, `missing end marker: ${end}`);
  return page.slice(from, to);
}

function migrationTarget(search, migrationCode = "single-use-code") {
  assert.ok(migrationScript, "liff/migrate.html script not found");
  const sandbox = {
    URL,
    URLSearchParams,
    location: {search},
  };
  vm.runInNewContext(
    `${migrationScript}\nthis.buildCurrentMigrationUrl = buildCurrentMigrationUrl;`,
    sandbox,
    {filename: "liff/migrate.html"},
  );
  return sandbox.buildCurrentMigrationUrl(migrationCode, search);
}

function functionSource(name) {
  const pattern = new RegExp(`(?:async\\s+)?function\\s+${name}\\s*\\(`);
  const match = pattern.exec(page);
  assert.ok(match, `missing function: ${name}`);
  const start = match.index;
  const brace = page.indexOf("{", start);
  let depth = 0;
  for (let index = brace; index < page.length; index += 1) {
    if (page[index] === "{") depth += 1;
    if (page[index] === "}") {
      depth -= 1;
      if (depth === 0) return page.slice(start, index + 1);
    }
  }
  throw new Error(`unterminated function: ${name}`);
}

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}

function expose(source, names, context = {}) {
  const sandbox = vm.createContext({ Promise, console, ...context });
  const exports = names.map((name) => `this.${name} = ${name};`).join("\n");
  new vm.Script(`${source}\n${exports}`).runInContext(sandbox);
  return sandbox;
}

test("registration failures explain refresh login and migrated-account recovery", () => {
  const sandbox = expose(
    functionSource("registrationFailureMessage"),
    ["registrationFailureMessage"],
  );

  assert.match(
    sandbox.registrationFailureMessage(401, {error: "invalid id_token"}),
    /LINE 登入已過期/,
  );
  assert.match(
    sandbox.registrationFailureMessage(409, {error: "account_migrated"}),
    /新版 LINE 入口/,
  );
  assert.match(
    sandbox.registrationFailureMessage(500, {}),
    /目前無法完成會員註冊/,
  );
});

test("expired registration token restarts LINE login on the same page", () => {
  const calls = [];
  const sandbox = expose(
    functionSource("recoverRejectedLineRegistration"),
    ["recoverRejectedLineRegistration"],
    {
      refreshRejectedLineLogin: () => {
        calls.push("refresh");
        return true;
      },
      showLineLoginRequired: () => calls.push("generic-error"),
      readSafeDeepLinkParams: () => ({open: "onboarding"}),
    },
  );

  const recovered = sandbox.recoverRejectedLineRegistration(
    {status: 401},
    {error: "invalid_token"},
  );

  assert.equal(recovered, true);
  assert.deepEqual(calls, ["refresh"]);
});

test("first status renders without waiting for contacts or onboarding", async () => {
  const contacts = deferred();
  const onboarding = deferred();
  const events = [];
  const elements = {
    mvpSafeBtn: { disabled: true },
    mvpGuardStartBtn: { disabled: true },
  };
  const sandbox = expose(
    section("async function loadInitialMemberData()", "// 整合到 initApp"),
    ["loadInitialMemberData"],
    {
      apiGetStatus: async () => ({ is_today_checked: false, contacts: [] }),
      apiGetContacts: () => contacts.promise,
      fetchOnboardingState: () => onboarding.promise,
      renderStatus: () => events.push("status"),
      syncCheckBtn: () => events.push("sync"),
      renderSosAccess: () => events.push("sos"),
      renderGuardians: () => events.push("contacts"),
      renderMemberCenter: () => events.push("member"),
      friendlyApiFailure: () => "bad status",
      contactData: [],
      currentContactLimit: 1,
      lineUserId: "U123",
      pendingInitialStatusPromise: null,
      memberBootstrapState: {
        statusReady: false,
        dataReady: false,
        inFlight: null,
        error: null,
      },
      setMemberInteractionLocked() {},
      $: (id) => elements[id] || null,
      document: { body: { removeAttribute() {} } },
    },
  );

  const result = sandbox.loadInitialMemberData();
  await new Promise((resolve) => setImmediate(resolve));
  assert.deepEqual(events.slice(0, 3), ["status", "sync", "sos"]);

  contacts.resolve({ status: 200, data: { contacts: [], contact_limit: 1 } });
  onboarding.resolve({ done: true, hasGuardian: true, data: {} });
  await result;
});

test("member status prefetch starts as soon as LINE identity is known and is reused", async () => {
  const status = deferred();
  let statusRequests = 0;
  const sandbox = expose(
    [
      functionSource("startMemberStatusPrefetch"),
      section("async function loadInitialMemberData()", "// 整合到 initApp"),
    ].join("\n"),
    ["startMemberStatusPrefetch", "loadInitialMemberData"],
    {
      apiGetStatus: () => {
        statusRequests += 1;
        return status.promise;
      },
      apiGetContacts: async () => ({ status: 200, data: { contacts: [] } }),
      fetchOnboardingState: async () => ({ done: true, hasGuardian: true, data: {} }),
      renderStatus() {},
      syncCheckBtn() {},
      renderSosAccess() {},
      renderGuardians() {},
      renderMemberCenter() {},
      friendlyApiFailure: () => "bad status",
      contactData: [],
      currentContactLimit: 1,
      lineUserId: "U123",
      useLocalMode: false,
      pendingInitialStatusPromise: null,
      memberBootstrapState: {
        statusReady: false,
        dataReady: false,
        inFlight: null,
        error: null,
      },
      setMemberInteractionLocked() {},
      $: () => null,
      document: { body: { removeAttribute() {} } },
    },
  );

  sandbox.startMemberStatusPrefetch();
  assert.equal(statusRequests, 1);

  const initial = sandbox.loadInitialMemberData();
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(statusRequests, 1);

  status.resolve({ is_today_checked: true, plan: "paid_799_year", contacts: [] });
  const result = await initial;
  assert.equal(result.status.plan, "paid_799_year");
  assert.equal(statusRequests, 1);
});

test("same-day confirmed check-in cache renders before the status request finishes", () => {
  const rendered = [];
  const storage = new Map();
  storage.set(
    "alive_member_status_v1:U123",
    JSON.stringify({
      saved_at: Date.now(),
      status: {
        plan: "trial",
        is_today_checked: true,
        checkin_date: "2026-07-30",
      },
    }),
  );
  const elements = {
    dailyStatus: { textContent: "" },
  };
  const sandbox = expose(
    [
      functionSource("memberStatusCacheKey"),
      functionSource("readCachedMemberStatus"),
      functionSource("renderCachedCheckinStatus"),
    ].join("\n"),
    ["renderCachedCheckinStatus"],
    {
      MEMBER_STATUS_CACHE_PREFIX: "alive_member_status_v1:",
      MEMBER_STATUS_CACHE_MAX_AGE_MS: 24 * 60 * 60 * 1000,
      Date,
      localStorage: { getItem: (key) => storage.get(key) || null },
      getToday: () => "2026-07-30",
      syncCheckBtn: (status) => rendered.push(status),
      $: (id) => elements[id] || null,
    },
  );

  assert.equal(sandbox.renderCachedCheckinStatus("U123"), true);
  assert.equal(rendered.length, 1);
  assert.equal(rendered[0].is_today_checked, true);
  assert.equal(elements.dailyStatus.textContent, "今日已簽到");
});

test("yesterday's confirmed check-in cache never renders as checked today", () => {
  const rendered = [];
  const storage = new Map();
  storage.set(
    "alive_member_status_v1:U123",
    JSON.stringify({
      saved_at: Date.now(),
      status: {
        plan: "trial",
        is_today_checked: true,
        checkin_date: "2026-07-29",
      },
    }),
  );
  const sandbox = expose(
    [
      functionSource("memberStatusCacheKey"),
      functionSource("readCachedMemberStatus"),
      functionSource("renderCachedCheckinStatus"),
    ].join("\n"),
    ["renderCachedCheckinStatus"],
    {
      MEMBER_STATUS_CACHE_PREFIX: "alive_member_status_v1:",
      MEMBER_STATUS_CACHE_MAX_AGE_MS: 24 * 60 * 60 * 1000,
      Date,
      localStorage: { getItem: (key) => storage.get(key) || null },
      getToday: () => "2026-07-30",
      syncCheckBtn: (status) => rendered.push(status),
      $: () => null,
    },
  );

  assert.equal(sandbox.renderCachedCheckinStatus("U123"), false);
  assert.equal(rendered.length, 0);
});

test("successful check-in immediately persists today's confirmed state", async () => {
  const storage = new Map();
  const button = {
    disabled: false,
    dataset: { state: "pending" },
    setAttribute() {},
    innerHTML: "",
  };
  const sandbox = expose(
    [
      functionSource("memberStatusCacheKey"),
      functionSource("writeCachedMemberStatus"),
      functionSource("doCheckin"),
    ].join("\n"),
    ["doCheckin"],
    {
      MEMBER_STATUS_CACHE_PREFIX: "alive_member_status_v1:",
      CHECK_BTN_LOADING_HTML: "loading",
      requireMemberActionReady: () => true,
      useLocalMode: false,
      lineUserId: "U123",
      appBootstrapPromise: null,
      appBootstrapComplete: true,
      currentStatusData: null,
      getToday: () => "2026-07-30",
      apiCheckin: async () => ({ ok: true, plan: "trial", history: [] }),
      localStorage: { setItem: (key, value) => storage.set(key, value) },
      $: (id) => (id === "checkBtn" ? button : null),
      hideInlineError() {},
      renderStatus(status) {
        sandbox.currentStatusData = status;
        button.dataset.state = "checked";
      },
      showCheckinSuccessMessage() {},
      showInlineError() {},
      syncCheckBtn() {},
      showLineLoginRequired() {},
    },
  );

  await sandbox.doCheckin();

  const cached = JSON.parse(storage.get("alive_member_status_v1:U123"));
  assert.equal(cached.status.is_today_checked, true);
  assert.equal(cached.status.checkin_date, "2026-07-30");
});

test("canonical action keeps page and open aliases on the requested screen", () => {
  const parserSource = section(
    "function requestedAppAction()",
    "function setInitialRouteLoading",
  );
  const routeSource = section("function openRequestedPage()", "function openUpgradePlans()");
  const params = {};
  const tabs = [];
  const sandbox = expose(
    `${parserSource}\n${routeSource}`,
    ["requestedAppAction", "openRequestedPage"],
    {
      getAppParam: (key) => params[key] || "",
      showTab: (tab) => tabs.push(tab),
      openMvpGuardPanel: () => tabs.push("guard"),
      openSosModal: () => tabs.push("sos"),
      setCalendarExpanded() {},
      setMemberCenterExpanded() {},
      document: { querySelector: () => null },
      window: { location: { href: "" } },
    },
  );

  for (const [query, expected] of [
    [{ page: "member" }, "member"],
    [{ page: "guardians" }, "guardians"],
    [{ open: "profile" }, "member"],
    [{ open: "member" }, "member"],
    [{ open: "safety" }, "guard"],
  ]) {
    Object.keys(params).forEach((key) => delete params[key]);
    Object.assign(params, query);
    tabs.length = 0;
    sandbox.openRequestedPage();
    assert.equal(tabs.at(-1), expected);
  }
});

test("shared member gate blocks status and full-data actions until ready", () => {
  const gateSource = section(
    "function requireMemberActionReady(",
    "function showMemberBootstrapError(",
  );
  const notices = [];
  const sandbox = expose(gateSource, ["requireMemberActionReady"], {
    useLocalMode: false,
    lineUserId: "",
    memberBootstrapState: { statusReady: false, dataReady: false },
    showMemberBootstrapPending: (message) => notices.push(message),
    showLineLoginRequired: () => notices.push("login"),
    readSafeDeepLinkParams: () => ({}),
  });

  assert.equal(sandbox.requireMemberActionReady("status"), false);
  sandbox.lineUserId = "U123";
  assert.equal(sandbox.requireMemberActionReady("status"), false);
  sandbox.memberBootstrapState.statusReady = true;
  assert.equal(sandbox.requireMemberActionReady("status"), true);
  assert.equal(sandbox.requireMemberActionReady("data"), false);
  sandbox.memberBootstrapState.dataReady = true;
  assert.equal(sandbox.requireMemberActionReady("data"), true);
  assert.ok(notices.length >= 2);
});

test("retry reruns only member bootstrap and unlocks after success", async () => {
  const retrySource = section(
    "async function retryMemberBootstrap()",
    "async function loadInitialMemberData()",
  );
  let calls = 0;
  const sandbox = expose(retrySource, ["retryMemberBootstrap"], {
    useLocalMode: false,
    lineUserId: "U123",
    memberBootstrapState: {
      statusReady: false,
      dataReady: false,
      inFlight: null,
    },
    initApp: async () => {
      calls += 1;
      sandbox.memberBootstrapState.statusReady = true;
      sandbox.memberBootstrapState.dataReady = true;
      return true;
    },
    setMemberInteractionLocked() {},
    hideInlineError() {},
  });

  const result = await sandbox.retryMemberBootstrap();
  assert.equal(result, true);
  assert.equal(calls, 1);
  assert.equal(sandbox.memberBootstrapState.statusReady, true);
  assert.equal(sandbox.memberBootstrapState.dataReady, true);
  assert.equal(page.includes("location.reload()"), false);
});

test("member mutations execute the shared gate before any operation", async () => {
  const names = [
    "doCheckin",
    "submitSmartReminderEditor",
    "deleteSmartReminder",
    "saveMemberDailyReminder",
    "shareMyLocation",
    "refreshSafetyGuardLocation",
    "stopLocationSharing",
    "deleteCheckinHistory",
    "deleteAccountAndData",
    "openAddGuardianFromMember",
    "sendSosAlert",
    "saveGuardian",
    "executeDeleteGuardian",
    "saveMvpContact",
    "saveContacts",
    "saveSelectedCalendarNote",
    "unbindGuardianGroup",
  ];
  const calls = [];
  const sandbox = expose(
    names.map(functionSource).join("\n"),
    names,
    {
      requireMemberActionReady: (scope) => {
        calls.push(scope);
        return false;
      },
      setMemberReminderSaveFeedback() {},
    },
  );

  for (const name of names) {
    const result = await sandbox[name]();
    assert.equal(result, false, `${name} must stop when gate is closed`);
  }
  assert.equal(calls.length, names.length);
  assert.ok(calls.includes("status"));
  assert.ok(calls.includes("data"));
});

test("status error renders senior-readable retry without page reload", () => {
  const listeners = {};
  const errorBox = {
    classList: { remove() {} },
    hidden: true,
    innerHTML: "",
  };
  const retryButton = {
    addEventListener: (type, handler) => {
      listeners[type] = handler;
    },
  };
  let retries = 0;
  const sandbox = expose(
    functionSource("showMemberBootstrapError"),
    ["showMemberBootstrapError"],
    {
      memberBootstrapState: {
        statusReady: true,
        dataReady: true,
        error: null,
      },
      setMemberInteractionLocked() {},
      retryMemberBootstrap: () => {
        retries += 1;
      },
      $: (id) => ({
        inlineError: errorBox,
        retryMemberBootstrapBtn: retryButton,
      })[id] || null,
    },
  );

  sandbox.showMemberBootstrapError(new Error("network"));
  assert.match(errorBox.innerHTML, /暫時讀不到會員資料/);
  assert.match(errorBox.innerHTML, /重新載入資料/);
  assert.equal(errorBox.hidden, false);
  listeners.click();
  assert.equal(retries, 1);
  assert.equal(page.includes("location.reload()"), false);
});

test("server guardian_required shows onboarding and blocks home, check-in, guard, and SOS routes", async () => {
  const initSource = section("async function initApp()", "// ===== D01");

  for (const openAction of ["home", "checkin", "guard", "sos"]) {
    const events = [];
    const sandbox = expose(`${functionSource("memberOnboardingGateDecision")}\n${initSource}`, ["initApp"], {
      lineUserId: "U-member",
      lineRegistrationWasExisting: false,
      pendingMigratedMemberData: null,
      location: { hash: "" },
      bindTabEvents() {},
      loadInitialMemberData: async () => ({
        status: {
          guardian_required: true,
          home_ready: false,
          contact_count: 1,
          bound_guardian_count: 0,
        },
        contacts: [{ name: "阿媽", binding_status: "unbound" }],
        onboarding: {
          guardian_required: true,
          home_ready: false,
          done: false,
          hasGuardian: true,
          data: { guardian_required: true, home_ready: false },
        },
      }),
      requestedAppAction: () => openAction,
      isInviteeDeepLink: () => false,
      currentGuardianContacts: () => [{ name: "阿媽", binding_status: "unbound" }],
      hasHomeSetupComplete: () => false,
      hasAnyGuardianOrContact: () => true,
      syncInviteUiForBoundState() {},
      clearShareFirstLocalFlags() {},
      closeGuardianPrompt() {},
      closeInviteAcceptPrompt() {},
      showOnboarding: async () => events.push("onboarding"),
      showTab: (tab) => events.push(`tab:${tab}`),
      openMvpGuardPanel: () => events.push("guard"),
      openSosFlow: () => events.push("sos"),
      doCheckin: async () => events.push("checkin"),
      $: () => null,
      showMemberBootstrapError: (error) => { throw error; },
    });

    await sandbox.initApp();
    assert.deepEqual(events, ["onboarding"], `${openAction} must stay behind the guardian gate`);
  }
});

test("guardian_required keeps member controls locked after bootstrap data arrives", async () => {
  const locks = [];
  const elements = {
    mvpSafeBtn: { disabled: true },
    mvpGuardStartBtn: { disabled: true },
  };
  const sandbox = expose(
    section("async function loadInitialMemberData()", "// 整合到 initApp"),
    ["loadInitialMemberData"],
    {
      apiGetStatus: async () => ({ guardian_required: true, home_ready: false, contacts: [] }),
      apiGetContacts: async () => ({ status: 200, data: { contacts: [], contact_limit: 1 } }),
      fetchOnboardingState: async () => ({ guardianRequired: true, homeReady: false, data: {} }),
      renderStatus() {},
      syncCheckBtn() {},
      renderSosAccess() {},
      renderGuardians() {},
      renderMemberCenter() {},
      friendlyApiFailure: () => "bad status",
      contactData: [],
      currentContactLimit: 1,
      lineUserId: "U-member",
      pendingInitialStatusPromise: null,
      memberBootstrapState: { statusReady: false, dataReady: false, error: null },
      setMemberInteractionLocked: (locked) => locks.push(locked),
      $: (id) => elements[id] || null,
      document: { body: { removeAttribute() {} } },
    },
  );

  await sandbox.loadInitialMemberData();
  assert.equal(sandbox.memberBootstrapState.statusReady, false);
  assert.equal(elements.mvpSafeBtn.disabled, true);
  assert.equal(elements.mvpGuardStartBtn.disabled, true);
  assert.ok(locks.every((locked) => locked === true));
});

test("registered B399 member with unfinished guardian setup resumes onboarding progress", async () => {
  const events = [];
  const sandbox = expose(`${functionSource("memberOnboardingGateDecision")}\n${functionSource("initApp")}`, ["initApp"], {
    lineUserId: "U-baby",
    lineRegistrationWasExisting: true,
    memberBootstrapState: { inFlight: null },
    pendingMigratedMemberData: null,
    location: { hash: "" },
    bindTabEvents() {},
    loadInitialMemberData: async () => ({
      status: {
        guardian_required: true,
        home_ready: false,
        plan: "paid_399_year",
        beta_cohort: "B399",
      },
      contacts: [],
      onboarding: {
        guardianRequired: true,
        homeReady: false,
        done: false,
        hasGuardian: false,
        data: { guardian_required: true, home_ready: false },
      },
    }),
    requestedAppAction: () => "onboarding",
    isInviteeDeepLink: () => false,
    syncInviteUiForBoundState() {},
    clearShareFirstLocalFlags() {},
    closeGuardianPrompt() {},
    closeInviteAcceptPrompt() {},
    showRegisteredMemberSetupReminder: () => events.push("member-reminder"),
    showOnboarding: async () => events.push("onboarding"),
    showTab: (tab) => events.push(`tab:${tab}`),
    bindGuardianEvents() {},
    bindMemberEvents() {},
    bindSmartReminderEvents() {},
    bindCalendarEvents() {},
    maybeShowGuardianComplete: async () => {},
    $: () => null,
    showMemberBootstrapError: (error) => { throw error; },
  });

  await sandbox.initApp();
  assert.deepEqual(events, ["onboarding"]);
});

test("guardian-required onboarding cannot be dismissed by an unbound contact", async () => {
  const closeVisibility = [];
  const steps = [];
  const elements = {
    onboardingModal: { hidden: true, dataset: {}, addEventListener() {}, scrollTop: 0 },
    onboardingError: { hidden: true, textContent: "" },
    obName: { value: "" },
    obPhone: { value: "" },
    obEmail: { value: "" },
  };
  const sandbox = expose(`${functionSource("onboardingResumeView")}\n${functionSource("showOnboarding")}`, ["showOnboarding"], {
    currentStatusData: { guardian_required: true },
    currentGuardianContacts: () => [{ name: "阿媽", binding_status: "unbound" }],
    fetchOnboardingState: async () => ({ guardianRequired: true, homeReady: false, data: {} }),
    setRelationshipValue() {},
    setOnboardingCloseVisible: (visible) => closeVisibility.push(visible),
    showOnboardingShareStep: () => steps.push("share"),
    showOnboardingGuardianStep: () => steps.push("profile"),
    showOnboardingReminderStep: () => steps.push("reminder"),
    fetchOnboardingState: async () => ({ ok: true, data: { completed_steps: {} } }),
    $: (id) => elements[id] || null,
  });

  await sandbox.showOnboarding();
  assert.deepEqual(closeVisibility, [false]);
  assert.deepEqual(steps, ["profile"]);
  assert.equal(elements.onboardingModal.hidden, false);
});

test("guardian_required blocks status actions even after status data is loaded", () => {
  const gateSource = section(
    "function requireMemberActionReady(",
    "function showMemberBootstrapError(",
  );
  const sandbox = expose(gateSource, ["requireMemberActionReady"], {
    useLocalMode: false,
    lineUserId: "U-member",
    memberBootstrapState: { guardianRequired: true, statusReady: true, dataReady: true },
    showMemberBootstrapPending() {},
    showLineLoginRequired() {},
    readSafeDeepLinkParams: () => ({}),
  });

  assert.equal(sandbox.requireMemberActionReady("status"), false);
});

test("legacy handoff parses nested liff.state and drops the old Provider inviter ID", () => {
  const oldProviderUserId = "U0123456789abcdef0123456789abcdef";
  const nestedState = encodeURIComponent(
    `/?open=guard&invite_from=${oldProviderUserId}&friend_invite=ABC1234&access_token=secret`,
  );

  assert.equal(
    migrationTarget(`?liff.state=${nestedState}`),
    "https://liff.line.me/2010848330-UAiqPPYD?migration_code=single-use-code&open=guard&friend_invite=ABC1234",
  );
});

test("legacy handoff forwards only non-identity allowlisted outer parameters", () => {
  const oldProviderUserId = "Ufedcba9876543210fedcba9876543210";

  assert.equal(
    migrationTarget(
      `?page=member&invite_from=${oldProviderUserId}&id_token=secret&unexpected=leak`,
    ),
    "https://liff.line.me/2010848330-UAiqPPYD?migration_code=single-use-code&page=member",
  );
});

test("legacy handoff never emits an old Provider user ID under an allowlisted key", () => {
  const oldProviderUserId = "U0123456789abcdef0123456789abcdef";

  for (const key of ["open", "page", "friend_invite"]) {
    assert.equal(
      migrationTarget(`?${key}=${oldProviderUserId}`),
      "https://liff.line.me/2010848330-UAiqPPYD?migration_code=single-use-code",
      `${key} must not carry a legacy LINE user ID`,
    );
  }
});

test("legacy handoff rejects token-like values hidden in allowlisted keys", () => {
  for (const [key, sensitive] of [
    ["open", "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJVMTIzIn0.signature"],
    ["page", "access_token_secret_value"],
    ["friend_invite", "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJVMTIzIn0.signature"],
    ["friend_invite", "TOO-LONG-INVITE-CODE-SECRET"],
  ]) {
    assert.equal(
      migrationTarget(`?${key}=${encodeURIComponent(sensitive)}`),
      "https://liff.line.me/2010848330-UAiqPPYD?migration_code=single-use-code",
      `${key} must reject sensitive or invalid values`,
    );
  }
});

test("logged-out LINE entry reaches explicit login without calling authenticated friendship API", async () => {
  const calls = [];
  const liff = {
    isLoggedIn: () => {
      calls.push("login");
      return false;
    },
    getFriendship: async () => {
      throw new Error("UNAUTHORIZED");
    },
  };
  const sandbox = expose(functionSource("resolveLineEntryGate"), ["resolveLineEntryGate"], {
    useLocalMode: false,
    window: { liff },
  });

  assert.equal(await sandbox.resolveLineEntryGate(), "login");
  assert.deepEqual(calls, ["login"]);
});

test("logged-in LINE entry verifies actual friendship before returning friend or ready", async () => {
  for (const [friendFlag, expected] of [
    [false, "friend"],
    [true, "ready"],
  ]) {
    const calls = [];
    const liff = {
      isLoggedIn: () => {
        calls.push("login");
        return true;
      },
      getFriendship: async () => {
        calls.push("friendship");
        return { friendFlag };
      },
    };
    const sandbox = expose(functionSource("resolveLineEntryGate"), ["resolveLineEntryGate"], {
      useLocalMode: false,
      window: { liff },
    });
    assert.equal(await sandbox.resolveLineEntryGate(), expected);
    assert.deepEqual(calls, ["login", "friendship"]);
  }
});

test("first-time unbound entry keeps the four-step setup guide visible across LINE and guardian gates", () => {
  const elements = {
    lineEntryGate: { hidden: true },
    lineEntryFriendStep: { hidden: true },
    lineEntryLoginStep: { hidden: true },
    lineGuideJoin: { dataset: {}, textContent: "" },
    lineGuideLogin: { dataset: {}, textContent: "" },
    onboardingShareStep: { hidden: true },
    onboardingGuardianStep: { hidden: true },
    onboardingReminderStep: { hidden: true },
    onboardingTitle: { textContent: "" },
    onboardingIntro: { textContent: "" },
    onboardingStepLabel: { textContent: "" },
    onboardingGuideJoin: { dataset: {}, textContent: "" },
    onboardingGuideLogin: { dataset: {}, textContent: "" },
    onboardingGuideProfile: { dataset: {}, textContent: "" },
    onboardingGuideGuardian: { dataset: {}, textContent: "" },
  };
  const classNames = new Set();
  const source = [
    functionSource("setSetupGuideState"),
    functionSource("setLineSetupGuideState"),
    functionSource("showLineEntryGate"),
    functionSource("showOnboardingGuardianStep"),
    functionSource("showOnboardingShareStep"),
  ].join("\n");
  const sandbox = expose(
    source,
    ["showLineEntryGate", "showOnboardingGuardianStep", "showOnboardingShareStep"],
    {
      $: (id) => elements[id] || null,
      setTimeout: (callback) => callback(),
      document: {
        body: {
          classList: {
            add: (name) => classNames.add(name),
          },
        },
      },
    },
  );

  sandbox.showLineEntryGate("friend");
  assert.equal(elements.lineEntryGate.hidden, false);
  assert.equal(elements.lineGuideJoin.dataset.state, "current");
  assert.equal(elements.lineGuideLogin.dataset.state, "upcoming");

  sandbox.showLineEntryGate("login");
  assert.equal(elements.lineGuideJoin.dataset.state, "done");
  assert.equal(elements.lineGuideLogin.dataset.state, "current");

  sandbox.showOnboardingGuardianStep();
  assert.equal(elements.onboardingGuideJoin.dataset.state, "done");
  assert.equal(elements.onboardingGuideLogin.dataset.state, "done");
  assert.equal(elements.onboardingGuideProfile.dataset.state, "current");
  assert.equal(elements.onboardingGuideGuardian.dataset.state, "upcoming");
  assert.match(elements.onboardingIntro.textContent, /守護人姓名/);

  sandbox.showOnboardingShareStep();
  assert.equal(elements.onboardingGuideProfile.dataset.state, "done");
  assert.match(elements.onboardingIntro.textContent, /核心守護人/);
});

test("explicit login click preserves only validated invite migration and route continuation", () => {
  const inviter = `U${"a".repeat(32)}`;
  const migrationCode = "m".repeat(43);
  const location = {
    origin: "https://alive-checkin.onrender.com",
    pathname: "/",
    search: (
      `?invite_from=${inviter}&friend_invite=ABC1234&open=guard`
      + `&migration_code=${migrationCode}&friendship_status_changed=true`
      + "&id_token=secret-token&access_token=access-secret&unexpected=leak"
    ),
    hash: "",
  };
  const loginCalls = [];
  const listeners = {};
  const loginButton = {
    dataset: {},
    addEventListener: (type, handler) => {
      listeners[type] = handler;
    },
  };
  const source = [
    section("const LOGIN_CONTINUATION_ACTIONS", "function isInviteeDeepLink"),
    section("function buildCleanLoginRedirectUri", "function setTheme"),
    functionSource("bindLineEntryGate"),
  ].join("\n");
  const sandbox = expose(
    source,
    [
      "readSafeDeepLinkParams",
      "buildCleanLoginRedirectUri",
      "startLineLogin",
      "bindLineEntryGate",
    ],
    {
      URLSearchParams,
      OAUTH_PARAM_KEYS: new Set([
        "code", "state", "liff.state", "liffClientId", "liffRedirectUri",
        "friendship_status_changed",
      ]),
      location,
      liff: {
        login: (options) => loginCalls.push(options),
      },
      window: {
        liff: {
          login: (options) => loginCalls.push(options),
        },
      },
      readAppParams: () => new URLSearchParams(location.search),
      readSafeDeepLinkParams: undefined,
      $: (id) => id === "lineEntryLoginBtn" ? loginButton : null,
      showLineLoginRequired() {},
    },
  );

  sandbox.bindLineEntryGate();
  listeners.click();

  assert.equal(loginCalls.length, 1);
  const redirect = new URL(loginCalls[0].redirectUri);
  assert.equal(redirect.origin, "https://alive-checkin.onrender.com");
  assert.equal(redirect.pathname, "/");
  assert.equal(redirect.searchParams.get("invite_from"), inviter);
  assert.equal(redirect.searchParams.get("friend_invite"), "ABC1234");
  assert.equal(redirect.searchParams.get("open"), "guard");
  assert.equal(redirect.searchParams.get("migration_code"), migrationCode);
  for (const forbidden of [
    "friendship_status_changed", "id_token", "access_token", "unexpected",
  ]) {
    assert.equal(redirect.searchParams.has(forbidden), false);
  }
  assert.doesNotMatch(redirect.toString(), /secret-token|access-secret|leak/);

  location.search = (
    `?open=${encodeURIComponent("eyJhbGciOiJIUzI1NiJ9.payload.signature")}`
    + `&migration_code=U${"b".repeat(32)}`
    + "&friend_invite=access_token_secret"
  );
  sandbox.startLineLogin();
  assert.equal(new URL(loginCalls[1].redirectUri).search, "");
});

test("friendship return rechecks and runs registration migration and member bootstrap once", async () => {
  let friendFlag = false;
  const calls = [];
  const liff = {
    init: async () => calls.push("init"),
    isLoggedIn: () => {
      calls.push("login-state");
      return true;
    },
    getFriendship: async () => {
      calls.push("friendship");
      return { friendFlag };
    },
    getProfile: async () => {
      calls.push("profile");
      return {
        userId: `U${"c".repeat(32)}`,
        displayName: "測試會員",
        pictureUrl: "",
      };
    },
  };
  const classNames = new Set(["line-entry-gated"]);
  const elements = {
    lineEntryGate: { hidden: false },
    lineEntryFriendStep: { hidden: false },
    lineEntryLoginStep: { hidden: true },
    lineGuideJoin: { dataset: {} },
    lineGuideLogin: { dataset: {} },
    lineGuideProfile: { dataset: {} },
    lineGuideGuardian: { dataset: {} },
  };
  const source = [
    functionSource("requestedAppAction"),
    functionSource("resolveLineEntryGate"),
    functionSource("setSetupGuideState"),
    functionSource("setLineSetupGuideState"),
    functionSource("showLineEntryGate"),
    functionSource("hideLineEntryGate"),
    functionSource("initializeLiff"),
    functionSource("recheckLineEntryGate"),
    functionSource("resumeMemberBootstrapAfterLineEntry"),
  ].join("\n");
  const sandbox = expose(
    source,
    ["initializeLiff", "recheckLineEntryGate"],
    {
      useLocalMode: false,
      withTimeout: async (promise) => promise,
      window: { liff },
      liff,
      appConfig: {},
      appConfigPromise: Promise.resolve({}),
      lineUserId: "",
      lineDisplayName: "",
      linePictureUrl: "",
      pendingMigratedMemberData: null,
      memberBootstrapState: {},
      renderCachedMemberStatus() {},
      renderCachedCheckinStatus() {},
      startMemberStatusPrefetch() {},
      $: (id) => elements[id] || null,
      document: {
        body: {
          classList: {
            add: (name) => classNames.add(name),
            remove: (name) => classNames.delete(name),
          },
        },
      },
      fetch: async (url) => {
        calls.push(url === "/api/line/register" ? "register" : "config");
        return {
          ok: true,
          json: async () => ({}),
        };
      },
      authHeaders: async () => ({Authorization: "Bearer current-id-token"}),
      getAppParam: (key) => ({
        friendship_status_changed: "true",
        migration_code: "m".repeat(43),
      })[key] || "",
      isInviteeDeepLink: () => false,
      maybeShowInviteAcceptPrompt() {},
      readSafeDeepLinkParams: () => ({}),
      formatLiffError: (error) => String(error && error.message || error),
      showLineLoginRequired: () => calls.push("generic-login-error"),
      sessionStorage: {
        getItem: () => null,
        removeItem() {},
      },
      hideInlineError: () => calls.push("clear-error"),
      redeemPendingAccountMigration: async () => {
        calls.push("migration");
        return {attempted: true, succeeded: true};
      },
      initApp: async () => {
        calls.push("member");
        return true;
      },
      applyInitialDeepLinkRoute: () => {
        calls.push("route");
        return {redirected: false};
      },
      refreshCalendarNotes: async () => calls.push("calendar"),
      refreshFriendLocations: async () => calls.push("friends"),
      openRequestedPage: () => calls.push("open"),
      renderStatus() {},
      buildLocalStatus() {},
      loadLocalState() {},
    },
  );

  assert.equal(await sandbox.recheckLineEntryGate(), false);
  assert.equal(elements.lineEntryFriendStep.hidden, false);
  assert.equal(elements.lineEntryLoginStep.hidden, true);
  assert.equal(calls.includes("profile"), false);
  assert.equal(calls.includes("register"), false);
  assert.equal(calls.includes("migration"), false);
  assert.equal(calls.includes("member"), false);

  friendFlag = true;
  const [first, second] = await Promise.all([
    sandbox.recheckLineEntryGate(),
    sandbox.recheckLineEntryGate(),
  ]);

  assert.equal(first, true);
  assert.equal(second, true);
  assert.equal(calls.filter((value) => value === "profile").length, 1);
  assert.equal(calls.filter((value) => value === "register").length, 1);
  assert.equal(calls.filter((value) => value === "migration").length, 1);
  assert.equal(calls.filter((value) => value === "member").length, 1);
  assert.equal(calls.filter((value) => value === "clear-error").length, 1);
  assert.equal(classNames.has("line-entry-gated"), false);
  assert.ok(
    calls.indexOf("friendship") < calls.indexOf("register")
      && calls.indexOf("register") < calls.indexOf("migration")
      && calls.indexOf("migration") < calls.indexOf("member"),
  );
});
