const form = document.getElementById("design-form");
const generateBtn = document.getElementById("generate-btn");
const emptyState = document.getElementById("empty-state");
const loadingState = document.getElementById("loading-state");
const noticeBanner = document.getElementById("notice-banner");
const resultEl = document.getElementById("result");
const floorplanPanel2d = document.getElementById("floorplan-panel-2d");
const floorplanPanel3d = document.getElementById("floorplan-panel-3d");
const view2dBtn = document.getElementById("view-2d-btn");
const view3dBtn = document.getElementById("view-3d-btn");
const scene3dContainer = document.getElementById("scene-3d-container");
const layoutNote = document.getElementById("layout-note");
const bundleTableBody = document.querySelector("#bundle-table tbody");
const totalPriceEl = document.getElementById("total-price");
const rationaleText = document.getElementById("rationale-text");
const optionsContainer = document.getElementById("options-container");
const refineForm = document.getElementById("refine-form");
const refineInput = document.getElementById("refine-input");
const refineBtn = document.getElementById("refine-btn");
const refineFeedback = document.getElementById("refine-feedback");

// Tracks the current design's inputs and full product bundle, so
// refinement requests know what's already selected and what room/budget
// constraints still apply.
let currentState = null;

const NOTICE_MESSAGES = {
  over_budget_fallback: "This budget doesn't quite cover a full bundle at standard options. Showing the closest possible combination instead.",
  stage_b_unavailable: "AI style reasoning is unavailable right now. Showing the highest-quality option that fits your space and budget instead.",
};

const CATEGORY_LABELS = {
  washbasin: "Washbasin", toilet: "Toilet", bathroom_faucet: "Bathroom Faucet",
  shower_fixture: "Shower Fixture", mirror: "Mirror",
};

form.addEventListener("submit", async (e) => {
  e.preventDefault();

  const payload = {
    room_width_ft: document.getElementById("room_width_ft").value,
    room_depth_ft: document.getElementById("room_depth_ft").value,
    budget_inr: document.getElementById("budget_inr").value,
    style: document.getElementById("style").value,
    layout: document.getElementById("layout").value,
  };

  setLoading();

  try {
    const res = await fetch("/api/design", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    render(data);
  } catch (err) {
    showError("Couldn't reach the design engine. Check that the server is running and try again.");
  }
});

function setLoading() {
  emptyState.hidden = true;
  resultEl.hidden = true;
  noticeBanner.hidden = true;
  loadingState.hidden = false;
  generateBtn.disabled = true;
  generateBtn.textContent = "Generating\u2026";
}

function resetButton() {
  generateBtn.disabled = false;
  generateBtn.textContent = "Generate design";
}

function showError(message) {
  loadingState.hidden = true;
  resultEl.hidden = true;
  noticeBanner.hidden = false;
  noticeBanner.classList.add("error");
  noticeBanner.textContent = message;
  resetButton();
}

function productDescription(p) {
  const parts = [p.finish, p.material].filter(Boolean);
  return parts.join(" \u00b7 ");
}

function renderLayoutNote(layout) {
  layoutNote.textContent = "";
  if (!layout) {
    layoutNote.hidden = true;
    return;
  }
  const title = document.createElement("strong");
  title.textContent = `Layout: ${layout.label}`;
  layoutNote.appendChild(title);
  const suffix = layout.auto ? " (chosen for your room)" : "";
  layoutNote.appendChild(document.createTextNode(suffix + (layout.reason ? ` \u2014 ${layout.reason}` : "")));
  layoutNote.hidden = false;
}

function renderBundleTable(products) {
  bundleTableBody.innerHTML = "";
  products.forEach((p) => {
    const desc = productDescription(p);
    const row = document.createElement("tr");
    row.innerHTML = `
      <td class="cat">${p.category.replace(/_/g, " ")}</td>
      <td class="name">${p.name}${desc ? `<span class="desc">${desc}</span>` : ""}</td>
      <td class="price">\u20b9${p.price_inr.toLocaleString("en-IN")}</td>
    `;
    bundleTableBody.appendChild(row);
  });
}

function renderAvailableOptions(availableOptions) {
  optionsContainer.innerHTML = "";
  if (!availableOptions) return;

  Object.entries(availableOptions).forEach(([category, options]) => {
    const block = document.createElement("div");
    block.className = "options-category";

    const label = document.createElement("p");
    label.className = "options-category-label";
    label.textContent = CATEGORY_LABELS[category] || category;
    block.appendChild(label);

    options.forEach((opt) => {
      const desc = productDescription(opt);
      const row = document.createElement("div");
      row.className = "option-row" + (opt.is_selected ? " selected" : "");
      row.innerHTML = `
        <span class="opt-name">${opt.name}${desc ? `<span class="opt-desc">${desc}</span>` : ""}</span>
        <span class="opt-price">\u20b9${opt.price_inr.toLocaleString("en-IN")}</span>
      `;
      block.appendChild(row);
    });

    optionsContainer.appendChild(block);
  });
}

function render(data) {
  loadingState.hidden = true;
  resetButton();

  if (data.status === "room_infeasible" || data.status === "no_valid_products" || data.status === "input_error") {
    showError(data.message);
    return;
  }

  if (data.status !== "ok") {
    showError("Something unexpected happened. Please try again.");
    return;
  }

  noticeBanner.classList.remove("error");
  if (data.notice && NOTICE_MESSAGES[data.notice]) {
    noticeBanner.hidden = false;
    noticeBanner.textContent = NOTICE_MESSAGES[data.notice];
  } else {
    noticeBanner.hidden = true;
  }

  floorplanPanel2d.innerHTML = data.svg;
  renderLayoutNote(data.layout);
  renderBundleTable(data.products);
  renderAvailableOptions(data.available_options);

  totalPriceEl.textContent = `\u20b9${data.total_price.toLocaleString("en-IN")}`;
  rationaleText.textContent = data.rationale;

  currentState = {
    room_width_ft: document.getElementById("room_width_ft").value,
    room_depth_ft: document.getElementById("room_depth_ft").value,
    budget_inr: document.getElementById("budget_inr").value,
    style: document.getElementById("style").value,
    // The layout actually used ("auto" already resolved), so refinements
    // are checked against the same arrangement.
    layout_id: data.layout.id,
    current_bundle: data.raw_bundle,
  };
  refineFeedback.hidden = true;
  refineInput.value = "";

  resultEl.hidden = false;

  if (data.scene_3d) {
    initOrUpdateScene3D(data.scene_3d);
  }
  showView("2d");
}

refineForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  if (!currentState) return;

  const message = refineInput.value.trim();
  if (!message) return;

  refineBtn.disabled = true;
  refineBtn.textContent = "Updating\u2026";
  refineFeedback.hidden = true;

  try {
    const res = await fetch("/api/refine", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...currentState, message }),
    });
    const data = await res.json();
    handleRefineResponse(data);
  } catch (err) {
    refineFeedback.hidden = false;
    refineFeedback.classList.add("error");
    refineFeedback.textContent = "Couldn't reach the design engine. Try again.";
  }

  refineBtn.disabled = false;
  refineBtn.textContent = "Update design";
});

function handleRefineResponse(data) {
  refineFeedback.hidden = false;

  if (data.status !== "ok") {
    refineFeedback.classList.add("error");
    refineFeedback.textContent = data.message;
    return;
  }

  refineFeedback.classList.remove("error");
  refineFeedback.textContent = data.change_message;

  floorplanPanel2d.innerHTML = data.svg;
  renderBundleTable(data.products);
  renderAvailableOptions(data.available_options);

  totalPriceEl.textContent = `\u20b9${data.total_price.toLocaleString("en-IN")}`;
  currentState.current_bundle = data.raw_bundle;
  refineInput.value = "";

  if (data.scene_3d) {
    initOrUpdateScene3D(data.scene_3d);
  }
}

// ---------------------------------------------------------------------
// View toggle (2D floorplan <-> 3D scene)
// ---------------------------------------------------------------------

function showView(view) {
  if (view === "2d") {
    floorplanPanel2d.hidden = false;
    floorplanPanel3d.hidden = true;
    view2dBtn.classList.add("active");
    view3dBtn.classList.remove("active");
  } else {
    floorplanPanel2d.hidden = true;
    floorplanPanel3d.hidden = false;
    view2dBtn.classList.remove("active");
    view3dBtn.classList.add("active");
    // Three.js needs a visible container to size the renderer correctly,
    // so re-trigger a resize once the panel is actually shown.
    onSceneContainerVisible();
  }
}

view2dBtn.addEventListener("click", () => showView("2d"));
view3dBtn.addEventListener("click", () => showView("3d"));

// ---------------------------------------------------------------------
// Three.js 3D scene rendering
// ---------------------------------------------------------------------
// This is a stylized visualization, not a CAD-precision render: floor
// footprints (toilet, vanity, shower zone) are exactly to scale, matching
// Stage A's real constraint math. Small accessory heights (faucet,
// mirror, showerhead) use reasonable standard placement assumptions,
// since exact mounting heights aren't in the product catalog.

let scene3d, camera3d, renderer3d, controls3d, roomGroup3d;

function initOrUpdateScene3D(sceneData) {
  if (!renderer3d) {
    setupScene3D();
  }
  buildRoom(sceneData);
}

function setupScene3D() {
  scene3d = new THREE.Scene();
  scene3d.background = new THREE.Color(0xeef1ef);

  camera3d = new THREE.PerspectiveCamera(50, 1, 1, 3000);

  renderer3d = new THREE.WebGLRenderer({ antialias: true });
  scene3dContainer.innerHTML = "";
  scene3dContainer.appendChild(renderer3d.domElement);

  const ambient = new THREE.AmbientLight(0xffffff, 0.7);
  scene3d.add(ambient);
  const dirLight = new THREE.DirectionalLight(0xffffff, 0.6);
  dirLight.position.set(100, 200, 100);
  scene3d.add(dirLight);

  controls3d = new THREE.OrbitControls(camera3d, renderer3d.domElement);
  controls3d.enableDamping = true;
  controls3d.dampingFactor = 0.08;

  animate3d();
}

function onSceneContainerVisible() {
  if (!renderer3d) return;
  const w = scene3dContainer.clientWidth || 600;
  const h = scene3dContainer.clientHeight || 460;
  renderer3d.setSize(w, h);
  camera3d.aspect = w / h;
  camera3d.updateProjectionMatrix();
}

function animate3d() {
  requestAnimationFrame(animate3d);
  if (controls3d) controls3d.update();
  if (renderer3d && scene3d && camera3d) renderer3d.render(scene3d, camera3d);
}

function buildRoom(sceneData) {
  if (roomGroup3d) {
    scene3d.remove(roomGroup3d);
  }
  roomGroup3d = new THREE.Group();

  const roomW = sceneData.room.width_in;
  const roomD = sceneData.room.depth_in;
  const roomH = sceneData.room.height_in;

  const floorGeo = new THREE.PlaneGeometry(roomW, roomD);
  const floorMat = new THREE.MeshStandardMaterial({ color: 0xf3f0ea, side: THREE.DoubleSide });
  const floor = new THREE.Mesh(floorGeo, floorMat);
  floor.rotation.x = -Math.PI / 2;
  floor.position.set(roomW / 2, 0, roomD / 2);
  roomGroup3d.add(floor);

  // Draw only the walls that are "behind" the fixtures from the camera's
  // point of view (chosen per layout by the backend), so nothing hides them.
  const wallMat = new THREE.MeshStandardMaterial({ color: 0xffffff, side: THREE.DoubleSide, transparent: true, opacity: 0.5 });
  const wallBuilders = {
    back: () => {
      const m = new THREE.Mesh(new THREE.PlaneGeometry(roomW, roomH), wallMat);
      m.position.set(roomW / 2, roomH / 2, 0);
      return m;
    },
    front: () => {
      const m = new THREE.Mesh(new THREE.PlaneGeometry(roomW, roomH), wallMat);
      m.position.set(roomW / 2, roomH / 2, roomD);
      return m;
    },
    left: () => {
      const m = new THREE.Mesh(new THREE.PlaneGeometry(roomD, roomH), wallMat);
      m.rotation.y = Math.PI / 2;
      m.position.set(0, roomH / 2, roomD / 2);
      return m;
    },
    right: () => {
      const m = new THREE.Mesh(new THREE.PlaneGeometry(roomD, roomH), wallMat);
      m.rotation.y = Math.PI / 2;
      m.position.set(roomW, roomH / 2, roomD / 2);
      return m;
    },
  };
  const cameraSpec = sceneData.camera;
  const wallsToDraw = (cameraSpec && cameraSpec.walls) || ["back", "left"];
  wallsToDraw.forEach((name) => roomGroup3d.add(wallBuilders[name]()));

  sceneData.objects.forEach((obj) => {
    // Three-tier fallback: real AI mesh (if present) -> procedural shape.
    // The procedural shape is added immediately so the scene is never
    // empty or waiting; if a real .glb exists for this category, it
    // loads asynchronously and swaps in once ready. If it fails to load
    // for any reason, the procedural shape already in place is untouched
    // — there is no failure mode where the fixture disappears.
    const fixtureGroup = new THREE.Group();
    fixtureGroup.scale.set(obj.w, obj.h, obj.d);
    fixtureGroup.position.set(obj.x, obj.y, obj.z);
    // Fixtures are modelled against the back wall; rot_y turns them to face
    // out from whichever wall their zone is on (rotation is about the
    // fixture's own origin corner, which the backend accounts for).
    fixtureGroup.rotation.y = obj.rot_y || 0;

    const placeholder = buildFixtureMesh(obj);
    fixtureGroup.add(placeholder);
    roomGroup3d.add(fixtureGroup);

    if (obj.mesh_url) {
      loadRealMesh(obj.mesh_url, fixtureGroup, placeholder);
    }
  });

  scene3d.add(roomGroup3d);

  if (cameraSpec) {
    camera3d.position.set(...cameraSpec.position);
    controls3d.target.set(...cameraSpec.target);
  } else {
    const dist = Math.max(roomW, roomD) * 1.05;
    camera3d.position.set(roomW / 2 + dist * 0.65, dist * 0.6, roomD + dist * 0.55);
    controls3d.target.set(roomW / 2, roomH / 4, roomD / 2);
  }
  controls3d.update();

  onSceneContainerVisible();
}

// ---------------------------------------------------------------------
// Real AI-generated mesh loading (optional top tier)
// ---------------------------------------------------------------------
// If a .glb exists for a category (see PRODUCT_MESHES_DIR on the backend),
// this loads it and normalizes it to fill the same unit cube (0..1 on
// every axis) that the procedural shapes use — so it inherits the exact
// same real-world scale/position from the parent group, with no special
// casing needed elsewhere. A raw AI-generated mesh has arbitrary size and
// origin, so normalization (center + rescale to fit the unit cube) is
// required before it can be dropped into the same coordinate convention.

const gltfLoader = new THREE.GLTFLoader();

function loadRealMesh(meshUrl, fixtureGroup, placeholder) {
  gltfLoader.load(
    meshUrl,
    (gltf) => {
      const model = gltf.scene;

      const box = new THREE.Box3().setFromObject(model);
      const size = new THREE.Vector3();
      box.getSize(size);
      const center = new THREE.Vector3();
      box.getCenter(center);

      // Guard against a degenerate/empty mesh (e.g. a failed export) —
      // if it has no real size, don't swap in something invisible.
      const maxDim = Math.max(size.x, size.y, size.z);
      if (!isFinite(maxDim) || maxDim <= 0) return;

      model.position.sub(center);               // center at origin
      const scale = 1 / maxDim;                  // fit within a unit cube
      model.scale.multiplyScalar(scale);
      model.position.multiplyScalar(scale);
      model.position.y += 0.5;                   // sit on the floor of the unit cube, not straddle it
      model.position.x += 0.5;
      model.position.z += 0.5;

      fixtureGroup.remove(placeholder);
      fixtureGroup.add(model);
    },
    undefined,
    (error) => {
      // Real mesh failed to load (missing file, malformed .glb, etc.) —
      // the procedural placeholder already in the scene is left exactly
      // as is. No visible failure, just no upgrade for this item.
      console.warn("Mesh load failed, keeping procedural shape:", meshUrl, error);
    }
  );
}

// ---------------------------------------------------------------------
// Procedural fixture shapes
// ---------------------------------------------------------------------
// Each family is built once, in a unit bounding box (0..1 on every axis),
// out of a handful of basic Three.js primitives combined into a
// recognizable silhouette — not a full per-SKU mesh. The parent group is
// then non-uniformly scaled to each product's own real w/h/d dimensions
// from the catalog, so every SKU in a family still renders at its true
// size even though the shape template is shared. This keeps the scene
// free, fast, dependency-free, and immune to the reliability problems of
// AI single-photo-to-3D reconstruction (rough geometry, external service
// dependency, cost) while still looking like real fixtures, not boxes.

function mat(color, opts = {}) {
  return new THREE.MeshStandardMaterial({ color: new THREE.Color(color), ...opts });
}

function buildFixtureMesh(obj) {
  const family = obj.shape_family;
  const color = obj.color;

  switch (family) {
    case "wall_hung_toilet": return buildWallHungToilet(color);
    case "vessel_basin": return buildVesselBasin(color);
    case "wall_mount_basin": return buildWallMountBasin(color);
    case "undercounter_basin": return buildVesselBasin(color); // close enough visually, time-boxed
    case "tall_faucet": return buildFaucet(color, true);
    case "standard_faucet": return buildFaucet(color, false);
    case "capsule_mirror": return buildCapsuleMirror(color);
    case "round_mirror": return buildRoundMirror(color);
    case "rectangular_mirror": return buildRectMirror(color);
    case "rainhead": return buildRainhead(color);
    case "showerhead": return buildShowerhead(color);
    default: return buildGenericBox(color, obj.transparent);
  }
}

function buildGenericBox(color, transparent) {
  const group = new THREE.Group();
  const geo = new THREE.BoxGeometry(1, 1, 1);
  const m = mat(color, transparent ? { transparent: true, opacity: 0.25 } : {});
  const mesh = new THREE.Mesh(geo, m);
  mesh.position.set(0.5, 0.5, 0.5);
  group.add(mesh);
  return group;
}

function buildWallHungToilet(color) {
  const group = new THREE.Group();
  const m = mat(color);

  // Tapered pedestal base
  const base = new THREE.Mesh(new THREE.CylinderGeometry(0.16, 0.28, 0.4, 16), m);
  base.position.set(0.5, 0.2, 0.55);
  group.add(base);

  // Bowl + seat, approximated as a rounded shape sized to a fraction of
  // the unit cube. The parent group's scale to the toilet's real w/h/d
  // gives it correct final proportions — no extra local flattening.
  const bowl = new THREE.Mesh(new THREE.SphereGeometry(0.42, 20, 16), m);
  bowl.position.set(0.5, 0.55, 0.42);
  group.add(bowl);

  // Concealed cistern / flush plate on the wall behind
  const plate = new THREE.Mesh(new THREE.BoxGeometry(0.5, 0.35, 0.06), m);
  plate.position.set(0.5, 0.85, 0.03);
  group.add(plate);

  return group;
}

function buildVesselBasin(color) {
  const group = new THREE.Group();
  const m = mat(color);
  // Sphere radius 0.5 fills the unit cube naturally; the parent group's
  // own non-uniform scale to the product's real w/h/d already gives it
  // correct bowl-like proportions (a basin's real height is naturally
  // much smaller than its width) — no extra local flattening needed.
  const bowl = new THREE.Mesh(new THREE.SphereGeometry(0.5, 20, 16), m);
  bowl.position.set(0.5, 0.5, 0.5);
  group.add(bowl);
  return group;
}

function buildWallMountBasin(color) {
  const group = new THREE.Group();
  const m = mat(color);
  const bowl = new THREE.Mesh(new THREE.SphereGeometry(0.5, 20, 16), m);
  bowl.position.set(0.5, 0.42, 0.5);
  group.add(bowl);
  const backsplash = new THREE.Mesh(new THREE.BoxGeometry(0.9, 0.5, 0.05), m);
  backsplash.position.set(0.5, 0.75, 0.05);
  group.add(backsplash);
  return group;
}

function buildFaucet(color, tall) {
  const group = new THREE.Group();
  const m = mat(color);
  const baseHeight = tall ? 0.75 : 0.45;

  const base = new THREE.Mesh(new THREE.CylinderGeometry(0.12, 0.14, baseHeight, 12), m);
  base.position.set(0.5, baseHeight / 2, 0.5);
  group.add(base);

  const neck = new THREE.Mesh(new THREE.TorusGeometry(0.22, 0.06, 8, 16, Math.PI), m);
  neck.rotation.z = Math.PI;
  neck.position.set(0.5, baseHeight, 0.5 - 0.22);
  group.add(neck);

  return group;
}

function roundedRectShape(w, h, r) {
  const shape = new THREE.Shape();
  shape.moveTo(-w / 2 + r, -h / 2);
  shape.lineTo(w / 2 - r, -h / 2);
  shape.quadraticCurveTo(w / 2, -h / 2, w / 2, -h / 2 + r);
  shape.lineTo(w / 2, h / 2 - r);
  shape.quadraticCurveTo(w / 2, h / 2, w / 2 - r, h / 2);
  shape.lineTo(-w / 2 + r, h / 2);
  shape.quadraticCurveTo(-w / 2, h / 2, -w / 2, h / 2 - r);
  shape.lineTo(-w / 2, -h / 2 + r);
  shape.quadraticCurveTo(-w / 2, -h / 2, -w / 2 + r, -h / 2);
  return shape;
}

function buildCapsuleMirror(color) {
  const group = new THREE.Group();
  const m = mat(color);
  const shape = roundedRectShape(1, 1, 0.45);
  const geo = new THREE.ExtrudeGeometry(shape, { depth: 0.06, bevelEnabled: false });
  const mesh = new THREE.Mesh(geo, m);
  mesh.position.set(0.5, 0.5, 0.47);
  group.add(mesh);
  return group;
}

function buildRoundMirror(color) {
  const group = new THREE.Group();
  const m = mat(color);
  const mesh = new THREE.Mesh(new THREE.CylinderGeometry(0.5, 0.5, 0.06, 28), m);
  mesh.rotation.x = Math.PI / 2;
  mesh.position.set(0.5, 0.5, 0.47);
  group.add(mesh);
  return group;
}

function buildRectMirror(color) {
  const group = new THREE.Group();
  const m = mat(color);
  const mesh = new THREE.Mesh(new THREE.BoxGeometry(1, 1, 0.06), m);
  mesh.position.set(0.5, 0.5, 0.47);
  group.add(mesh);
  return group;
}

function buildRainhead(color) {
  const group = new THREE.Group();
  const m = mat(color);
  const disc = new THREE.Mesh(new THREE.CylinderGeometry(0.5, 0.5, 0.15, 24), m);
  disc.position.set(0.5, 0.5, 0.5);
  group.add(disc);
  const arm = new THREE.Mesh(new THREE.CylinderGeometry(0.08, 0.08, 1.2, 8), m);
  arm.position.set(0.5, 1.1, 0.5);
  group.add(arm);
  return group;
}

function buildShowerhead(color) {
  const group = new THREE.Group();
  const m = mat(color);
  const head = new THREE.Mesh(new THREE.ConeGeometry(0.35, 0.4, 16), m);
  head.rotation.x = Math.PI;
  head.position.set(0.5, 0.5, 0.5);
  group.add(head);
  const arm = new THREE.Mesh(new THREE.CylinderGeometry(0.06, 0.06, 1.0, 8), m);
  arm.position.set(0.5, 1.0, 0.5);
  group.add(arm);
  return group;
}
