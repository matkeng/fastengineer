<!-- SPDX-License-Identifier: AGPL-3.0-only
     Copyright (C) 2026 Matthew Kelly -->
<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue';
import { loadSampleData, sampleSummary } from '../../lib/sampleData';
import { useKeyLists } from '../../stores/keylists';
import { useUi } from '../../stores/ui';
import EquipmentPackagesEditor from './EquipmentPackagesEditor.vue';
import LoadListEditor from './LoadListEditor.vue';
import CableTypesEditor from './CableTypesEditor.vue';
import CodeListEditor from './CodeListEditor.vue';
import EelEditor from './EelEditor.vue';
import PlcEditor from './PlcEditor.vue';
import DistributionPanelsEditor from './DistributionPanelsEditor.vue';
import InstrumentRunsheetEditor from './InstrumentRunsheetEditor.vue';
import MelListView from './MelListView.vue';
import MasterListView from './MasterListView.vue';
import EnumsEditor from './EnumsEditor.vue';
import RegisterEditor from './RegisterEditor.vue';
import LoadTypesEditor from './LoadTypesEditor.vue';
import MotorDataEditor from './MotorDataEditor.vue';
import DriveDataEditor from './DriveDataEditor.vue';
import StarterDataEditor from './StarterDataEditor.vue';
import LoadSummaryView from './LoadSummaryView.vue';
import PlantAreasEditor from './PlantAreasEditor.vue';

// The project's built-in lists; more are added to the sidebar.
const kl = useKeyLists();
const ui = useUi();
const TITLES = { 'plant-areas': 'Plant Areas', 'equipment-packages': 'Equipment Packages', 'load-types': 'Load Types', 'load-list': 'Project Master Load List', 'load-summary': 'Load List Summary Page',
	'equipment-codes': 'Equipment Codes', 'instrument-codes': 'Instrument Codes', eel: 'Electrical Equipment List', plc: 'PLC List',
	'cable-types': 'Cable Types', motors: 'Motor Data', drives: 'Drive Data', starters: 'Starter Coordination', 'distribution-panels': 'Distribution Panels', 'instrument-runsheet': 'Instrument Runsheet', mel: 'MEL', master: 'Project Master list', enums: 'Enums', 'drawing-list': 'Drawing List', 'document-list': 'Document List' };
const loaded = computed(() => !!{ 'plant-areas': kl.areasDraft, 'equipment-packages': kl.packagesDraft, 'load-types': kl.loadTypes, 'load-list': true, 'load-summary': true,
	'equipment-codes': kl.codeLists['equipment-codes'], 'instrument-codes': kl.codeLists['instrument-codes'], eel: kl.eel, plc: kl.plcDraft,
	'cable-types': kl.cableTypes, motors: true, drives: true, starters: true, 'distribution-panels': kl.panelsDraft, 'instrument-runsheet': kl.runsheetView, mel: kl.melList, master: kl.master, enums: kl.enumsDraft, 'drawing-list': kl.registers['drawing-list'], 'document-list': kl.registers['document-list'] }[kl.selected]);

onMounted(() => kl.load());

// Sample data: fills the lists that are still empty (a small invented plant), nothing else.
const sampleBusy = ref(false);
const sampleNote = ref('');
async function addSample() {
	sampleBusy.value = true;
	try {
		const res = await loadSampleData();
		await kl.load();
		sampleNote.value = sampleSummary(res) || 'Nothing was added: every list already has data.';
	} catch (err) {
		sampleNote.value = `The sample data could not be added: ${err instanceof Error ? err.message : String(err)}`;
	} finally {
		sampleBusy.value = false;
	}
}
// Coming back to the section shows what is saved now (a draft with unsaved changes is kept).
watch(() => ui.tab, (tab) => { if (tab === 'keylists') void kl.load(); });
</script>

<template>
	<div class="ref">
		<div class="ref-layout">
			<aside class="card ref-side">
				<section>
					<h3>Project lists</h3>
					<p class="hint">The key lists every project has. Their columns and rules are fixed.</p>
					<ul class="ref-nav">
						<li :class="{ current: kl.selected === 'plant-areas' }" @click="kl.select('plant-areas')">
							<span class="name">Plant Areas</span><span v-if="kl.areasDirty" class="dirty-dot" title="Unsaved changes">●</span>
							<span class="count" :title="`${kl.overview?.plant_areas.depth ?? 0} level(s)`">{{ kl.overview?.plant_areas.items ?? 0 }}</span>
						</li>
						<li :class="{ current: kl.selected === 'equipment-packages' }" @click="kl.select('equipment-packages')">
							<span class="name">Equipment Packages</span><span v-if="kl.packagesDirty" class="dirty-dot" title="Unsaved changes">●</span>
							<span class="count" :title="`package(s), with ${kl.overview?.equipment_packages.types ?? 0} equipment type(s)`">{{ kl.overview?.equipment_packages.items ?? 0 }}</span>
						</li>
						<li :class="{ current: kl.selected === 'load-types' }" @click="kl.select('load-types')">
							<span class="name">Load Types</span>
							<span class="count" title="load type(s)">{{ kl.overview?.load_types.items ?? 0 }}</span>
						</li>
						<li :class="{ current: kl.selected === 'equipment-codes' }" @click="kl.select('equipment-codes')">
							<span class="name">Equipment Codes</span>
							<span class="count" title="equipment code(s)">{{ kl.overview?.equipment_codes.items ?? 0 }}</span>
						</li>
						<li :class="{ current: kl.selected === 'instrument-codes' }" @click="kl.select('instrument-codes')">
							<span class="name">Instrument Codes</span>
							<span class="count" title="instrument code(s)">{{ kl.overview?.instrument_codes.items ?? 0 }}</span>
						</li>
						<li :class="{ current: kl.selected === 'cable-types' }" @click="kl.select('cable-types')">
							<span class="name">Cable Types</span>
							<span class="count" title="cable type(s)">{{ kl.overview?.cable_types.items ?? 0 }}</span>
						</li>
						<li :class="{ current: kl.selected === 'motors' }" title="Motors and their performance data (starts with WEG W22): <<Motor.FLC>>…" @click="kl.select('motors')">
							<span class="name">Motor Data</span>
							<span class="count" title="motor(s)">{{ kl.overview?.motors?.items ?? 0 }}</span>
						</li>
						<li :class="{ current: kl.selected === 'drives' }" title="Variable speed drives and their ratings (starts with PowerFlex 755TS): <<Drive.CatNo>>…" @click="kl.select('drives')">
							<span class="name">Drive Data</span>
							<span class="count" title="drive(s)">{{ kl.overview?.drives?.items ?? 0 }}</span>
						</li>
						<li :class="{ current: kl.selected === 'starters' }" title="Type 2 starter selections by motor kW (starts with NHP's 50 kA and 65 kA charts): <<Starter.CB>>…" @click="kl.select('starters')">
							<span class="name">Starter Coordination</span>
							<span class="count" title="row(s)">{{ kl.overview?.starters?.items ?? 0 }}</span>
						</li>
						<li :class="{ current: kl.selected === 'plc' }" @click="kl.select('plc')">
							<span class="name">PLC List</span><span v-if="kl.plcDirty || kl.catDirty" class="dirty-dot" title="Unsaved changes">●</span>
							<span class="count" :title="`${kl.overview?.plc.systems ?? 0} system(s), ${kl.overview?.plc.racks ?? 0} rack(s)`">{{ kl.overview?.plc.cards ?? 0 }}</span>
						</li>
					</ul>
				</section>
				<section>
					<h3>Loads and panels</h3>
					<p class="hint">The MEL (every row of the MEL imports, to read), the Electrical Equipment List, and the schedule of each distribution panel. The Load List is under Project master lists.</p>
					<ul class="ref-nav">
						<li :class="{ current: kl.selected === 'mel' }" @click="kl.select('mel')">
							<span class="name">MEL</span>
							<span class="count" title="row(s) in the MEL imports' latest files (read only)">{{ kl.overview?.mel?.items ?? 0 }}</span>
						</li>
						<li :class="{ current: kl.selected === 'eel' }" @click="kl.select('eel')">
							<span class="name">Electrical Equipment List</span>
							<span class="count" title="equipment item(s)">{{ kl.overview?.eel.items ?? 0 }}</span>
						</li>
						<li :class="{ current: kl.selected === 'distribution-panels' }" @click="kl.select('distribution-panels')">
							<span class="name">Distribution Panels</span><span v-if="kl.panelsDirty" class="dirty-dot" title="Unsaved changes">●</span>
							<span class="count" title="panel schedule(s)">{{ kl.overview?.distribution_panels?.items ?? 0 }}</span>
						</li>
					</ul>
				</section>
				<section>
					<h3>Instruments</h3>
					<p class="hint">What the Instrument generator will run from. Its rows refer to the equipment types, the plant areas, and the equipment of the MEL and the Electrical Equipment List.</p>
					<ul class="ref-nav">
						<li :class="{ current: kl.selected === 'instrument-runsheet' }" @click="kl.select('instrument-runsheet')">
							<span class="name">Instrument Runsheet</span><span v-if="kl.runsheetDirty" class="dirty-dot" title="Unsaved changes">●</span>
							<span class="count" title="row(s)">{{ kl.overview?.instrument_runsheet?.items ?? 0 }}</span>
						</li>
					</ul>
				</section>
				<section>
					<h3>Drawings and documents</h3>
					<p class="hint">The project's registers of drawings and of documents.</p>
					<ul class="ref-nav">
						<li :class="{ current: kl.selected === 'drawing-list' }" @click="kl.select('drawing-list')">
							<span class="name">Drawing List</span>
							<span class="count" title="drawing(s)">{{ kl.overview?.drawing_list?.items ?? 0 }}</span>
						</li>
						<li :class="{ current: kl.selected === 'document-list' }" @click="kl.select('document-list')">
							<span class="name">Document List</span>
							<span class="count" title="document(s)">{{ kl.overview?.document_list?.items ?? 0 }}</span>
						</li>
					</ul>
				</section>
				<section>
					<h3>Enums</h3>
					<p class="hint">The choices other lists pick from: disciplines, drawing types, document types and statuses.</p>
					<ul class="ref-nav">
						<li :class="{ current: kl.selected === 'enums' }" @click="kl.select('enums')">
							<span class="name">Enums</span><span v-if="kl.enumsDirty" class="dirty-dot" title="Unsaved changes">●</span>
							<span class="count" title="item(s) in the enums">{{ kl.overview?.enums?.items ?? 0 }}</span>
						</li>
					</ul>
				</section>
				<section>
					<h3>Project master lists</h3>
					<p class="hint">The Load List (every load of the imports and the Electrical Equipment List, with what is allocated to it), and one of each list the Power and Instrument generators fill together. Deliverables are made from them.</p>
					<ul class="ref-nav">
						<li :class="{ current: kl.selected === 'load-list' }" @click="kl.select('load-list')">
							<span class="name">Load List</span>
							<span class="count" :class="{ warn: kl.overview?.load_list.unallocated }"
								:title="`${kl.overview?.load_list.rows ?? 0} row(s), ${kl.overview?.load_list.unallocated ?? 0} without a plant area or load type`">{{ kl.overview?.load_list.rows ?? 0 }}</span>
						</li>
						<li :class="{ current: kl.selected === 'load-summary' }" title="Totals of the Load List: transformer and MCC loading…" @click="kl.select('load-summary')">
							<span class="name">Load List Summary</span>
						</li>
						<li v-for="m in kl.masters" :key="m.key" :class="{ current: kl.selected === 'master' && kl.masterKey === m.key }"
							@click="kl.masterKey = m.key; kl.select('master')">
							<span class="name">{{ m.name.replace('Project Master ', '') }}</span>
							<span class="count" :title="`${m.power_rows} from Power, ${m.instrument_rows} from Instrument`">{{ m.rows }}</span>
						</li>
					</ul>
				</section>
				<section>
					<h3>Sample data</h3>
					<p class="hint">Fills every list that is still empty with a small invented plant. Lists that already have data are left as they are.</p>
					<button type="button" class="secondary small" :disabled="sampleBusy" @click="addSample">{{ sampleBusy ? 'Adding…' : 'Add sample data' }}</button>
					<p v-if="sampleNote" class="hint small">{{ sampleNote }}</p>
				</section>
			</aside>
			<!-- v-show keeps each list's filter and expanded rows when switching between them -->
			<PlantAreasEditor v-if="kl.areasDraft" v-show="kl.selected === 'plant-areas'" />
			<EquipmentPackagesEditor v-if="kl.packagesDraft" v-show="kl.selected === 'equipment-packages'" />
			<LoadTypesEditor v-if="kl.loadTypes" v-show="kl.selected === 'load-types'" />
			<CodeListEditor v-if="kl.codeLists['equipment-codes']" v-show="kl.selected === 'equipment-codes'" list-id="equipment-codes" />
			<CodeListEditor v-if="kl.codeLists['instrument-codes']" v-show="kl.selected === 'instrument-codes'" list-id="instrument-codes" />
			<CableTypesEditor v-if="kl.cableTypes" v-show="kl.selected === 'cable-types'" />
			<MotorDataEditor v-if="kl.selected === 'motors'" />
			<DriveDataEditor v-if="kl.selected === 'drives'" />
			<StarterDataEditor v-if="kl.selected === 'starters'" />
			<EelEditor v-if="kl.eel" v-show="kl.selected === 'eel'" />
			<PlcEditor v-if="kl.plcDraft" v-show="kl.selected === 'plc'" />
			<LoadListEditor v-if="kl.selected === 'load-list'" />
			<LoadSummaryView v-if="kl.selected === 'load-summary'" />
			<DistributionPanelsEditor v-if="kl.panelsDraft" v-show="kl.selected === 'distribution-panels'" />
			<InstrumentRunsheetEditor v-if="kl.runsheetView" v-show="kl.selected === 'instrument-runsheet'" />
			<MelListView v-if="kl.melList" v-show="kl.selected === 'mel'" />
			<MasterListView v-if="kl.master && kl.selected === 'master'" />
			<EnumsEditor v-if="kl.enumsDraft && kl.enumsView" v-show="kl.selected === 'enums'" />
			<RegisterEditor v-if="kl.registers['drawing-list']" v-show="kl.selected === 'drawing-list'" kind="drawing-list" />
			<RegisterEditor v-if="kl.registers['document-list']" v-show="kl.selected === 'document-list'" kind="document-list" />
			<section v-if="!loaded" class="card wizard ref-empty">
				<h2>{{ TITLES[kl.selected] }}</h2>
				<p v-if="kl.error" class="error">{{ kl.error }}</p>
				<p v-else class="hint">Loading…</p>
			</section>
		</div>
	</div>
</template>
