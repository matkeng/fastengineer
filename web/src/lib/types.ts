// Hand-written for the PoC. In the real app these are generated from the
// Pydantic models in workbench_core so both sides share one schema (spec 7.1).
export interface EngineInfo {
	core_version: string;
	python: string;
	platform: string;
	pid: number;
	compiled: boolean;
}

export interface Greeting {
	message: string;
	at: string;
}

export interface Equipment {
	id: string;
	tag: string;
	description: string;
	rating_kw: number | null;
	views: string[];
}
