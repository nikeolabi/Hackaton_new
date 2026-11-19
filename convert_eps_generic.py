import json, uuid, re, html, datetime, collections, argparse
from zoneinfo import ZoneInfo
from pathlib import Path
parser = argparse.ArgumentParser(description="Map a patient source JSON to an EU EPS FHIR document candidate. Supports kemlab*, medlist*, vardokument* source records.")
parser.add_argument('input', help='Patient JSON input path')
parser.add_argument('-o', '--output', help='Output FHIR Bundle JSON filename or path')
parser.add_argument('--output-dir', help='Directory for generated JSON and mapping report')
parser.add_argument('--report', help='Mapping report JSON path')
parser.add_argument('--vitals-as-narrative', action='store_true', help='Keep vital signs in Composition narrative instead of Observation resources; workaround for overlapping IPS Bundle observation slices')
parser.add_argument('--document-date', help='Document date/time with timezone, e.g. 2026-11-18T14:00:00+01:00')
args = parser.parse_args()
src = json.loads(Path(args.input).read_text(encoding='utf-8'))
records = src.get('sources', [])
if not isinstance(records, list):
    raise ValueError('Expected a sources array in the input JSON')
index = {r.get('recordType'): i for i, r in enumerate(records) if isinstance(r, dict)}
med_i = next((i for i, r in enumerate(records) if re.fullmatch(r'medlist\d*', str(r.get('recordType','')))), None)
care_i = next((i for i, r in enumerate(records) if re.fullmatch(r'vardokument\d*', str(r.get('recordType','')))), None)
lab_i = [i for i, r in enumerate(records) if str(r.get('recordType', '')).startswith('kemlab')]
if not (med_i is not None or care_i is not None or lab_i):
    raise ValueError('No supported record types found; requires medlist*, vardokument* and/or kemlab*')
pid = str(src.get('patientId') or next((r.get('patientId') for r in records if r.get('patientId')), ''))
if not pid:
    raise ValueError('Missing patientId; cannot construct patient resource')
ns = uuid.UUID('a1d266b0-22bb-4c54-9d8d-28c2435024c1')
now = datetime.datetime.now(ZoneInfo('Europe/Stockholm')).replace(microsecond=0).isoformat()
doc_date = args.document_date or now
if datetime.datetime.fromisoformat(doc_date).utcoffset() is None:
    raise ValueError('Document datetime must include timezone')
def uid(k):return str(uuid.uuid5(ns,pid+':'+k))
def url(k):return 'urn:uuid:'+uid(k)
def date(v):
 if not v:return None
 s=str(v);return s[:4]+'-'+s[4:6]+'-'+s[6:8] if len(s)>=8 and s[:8].isdigit() else s[:10]
def dt(v):
 s=str(v or '');return date(s)+'T'+s[8:10]+':'+s[10:12]+':'+(s[12:14] if len(s)>=14 else '00')+'+01:00' if len(s)>=12 and s[:12].isdigit() else None
def aslist(x):return x if isinstance(x,list) else ([x] if x else [])
def xhtml(s):return '<div xmlns="http://www.w3.org/1999/xhtml"><p>'+html.escape(str(s))+'</p></div>'
def coding(system,code,display=None):
 d={'code':str(code)}
 if system:d['system']=system
 if display:d['display']=display
 return d
def cc(system,code,display):return {'coding':[coding(system,code,display)],'text':display}
entries=[]; provenance=[]; counts=collections.Counter()
def add(resource,key,source=None):
 resource['id']=uid(key);entries.append({'fullUrl':url(key),'resource':resource});counts[resource['resourceType']]+=1
 if source:provenance.append({'fhirReference':url(key),'sourcePath':source})
 return url(key)
patient_record = next((r.get('sourceData',{}).get('attestation',{}).get('patient', {})
                       for r in records if isinstance(r.get('sourceData'),dict)
                       and isinstance(r.get('sourceData',{}).get('attestation'),dict)
                       and r['sourceData']['attestation'].get('patient')), {})
name = patient_record.get('fullName') or 'Patient '+pid
pref=url('patient')
# Patient: keep original identifier; gender and birthDate are not asserted as source facts
patient={'resourceType':'Patient','meta':{'profile':['http://hl7.eu/fhir/eps/StructureDefinition/patient-eu-eps']},'identifier':[{'system':'http://electronichealth.se/identifier/personnummer','value':pid}], 'name':[{'text':name}], 'text':{'status':'generated','div':xhtml('Patient: '+name)}}
# author and custodian: organization with actual source care unit
care_unit = next((r['sourceData']['attestation']['careUnit'] for r in records
                  if isinstance(r.get('sourceData'), dict)
                  and isinstance(r['sourceData'].get('attestation'), dict)
                  and isinstance(r['sourceData']['attestation'].get('careUnit'), dict)), {})
orgname=care_unit.get('name') or 'Source healthcare organization (unidentified)'
orgref=url('org')
org={'resourceType':'Organization','name':orgname,'text':{'status':'generated','div':xhtml(orgname)}}
# Omit absent identifiers entirely; empty arrays are not valid populated FHIR elements.
if care_unit.get('id') is not None and str(care_unit['id']).strip():
    org['identifier']=[{'value':str(care_unit['id'])}]
sectiondefs=[('Allergies and intolerances','48765-2','Allergies and adverse reactions Document'),('Problem list','11450-4','Problem list - Reported'),('Medication list','10160-0','History of Medication use Narrative'),('Immunizations','11369-6','History of Immunization note'),('Relevant diagnostic tests and laboratory data','30954-2','Relevant diagnostic tests/laboratory data note'),('Medical devices','46264-8','History of medical device use'),('Plan of care','18776-5','Plan of care note'),('History of procedures','47519-4','History of Procedures Document')]
sections={title:{'title':title,'code':cc('http://loinc.org',code,display),'text':{'status':'generated','div':xhtml('No information available in supplied records.')}} for title,code,display in sectiondefs}
section_entries=collections.defaultdict(list);section_lines=collections.defaultdict(list)
def attach(title,ref,line):section_entries[title].append({'reference':ref});section_lines[title].append(str(line))
# diagnosis keyword values
for di,r in enumerate(records[care_i].get('records',[]) if care_i is not None else []):
 for ki,k in enumerate(r['keywords']):
  if k['name']!='Diagnos enl ICD-10':continue
  for vi,val in enumerate(k['values']):
   original=str(val.get('value',''));match=re.match(r'^([A-Z]\d{2}\d{0,2})\s+(.+)$',original)
   if not match:continue
   code,display=match.groups(); key=f'condition:{r["document_id"]}:{ki}:{vi}'
   condition={'resourceType':'Condition','meta':{'profile':['http://hl7.eu/fhir/base/StructureDefinition/condition-eu-core']},'code':cc(None,code,display),'subject':{'reference':pref},'recordedDate':date(r.get('event_date_time')),'note':[{'text':'Original diagnosis coding recorded as Diagnos enl ICD-10; code system version not independently verified.'}],'text':{'status':'generated','div':xhtml(original)}}
   ref=add(condition,key,f'$.sources[{care_i}].records[{di}].keywords[{ki}].values[{vi}]');attach('Problem list',ref,original)
# medication source history, each source order kept separately (no reconciliation / invented active status)
for mi,r in enumerate(records[med_i].get('records',[]) if med_i is not None else []):
 drugs=aslist(r.get('drugs',{}).get('drug'))
 for dj,drug in enumerate(drugs):
  medname=drug.get('preparation_text') or drug.get('atc_name') or 'Medication unspecified';strength=str(drug.get('strength') or '')+' '+str(drug.get('strength_unit') or '');desc=' '.join(v for v in [medname,strength.strip(),drug.get('dose_form')] if v)
  key=f'med:{r["document_id"]}:{dj}';medref=add({'resourceType':'Medication','meta':{'profile':['http://hl7.eu/fhir/base/StructureDefinition/medication-eu-core']},'code':cc('http://www.whocc.no/atc',drug['atc_code'],desc) if drug.get('atc_code') else {'text':desc},'text':{'status':'generated','div':xhtml(desc)}},key,f'$.sources[{med_i}].records[{mi}].drugs.drug[{dj}]')
  p=r.get('prescription') or {};start=date(p.get('first_dose_date'));end=date(p.get('last_dose_date'));period={}
  if start:period['start']=start
  if end:period['end']=end
  dosages=[str(d.get('dosage_instruction')) for d in aslist((r.get('days') or {}).get('day')) if d.get('dosage_instruction')]
  if not dosages:dosages=[str(d.get('dosage_drugs',{}).get('dosage_drug',{}).get('dose_text')) for d in aslist((r.get('dosages') or {}).get('dosage')) if isinstance(d.get('dosage_drugs',{}).get('dosage_drug'),dict)]
  dose_text='; '.join(dict.fromkeys(dosages)) if dosages else 'Dosage not specified in extracted record'
  status='completed' if end else 'unknown' # do NOT infer active from missing end date
  ms={'resourceType':'MedicationStatement','meta':{'profile':['http://hl7.eu/fhir/eps/StructureDefinition/MedicationStatement-eu-eps']},'status':status,'medicationReference':{'reference':medref,'display':desc},'subject':{'reference':pref},'dosage':[{'text':dose_text}], 'identifier':[{'value':r['document_id']}], 'text':{'status':'generated','div':xhtml(f'{desc}; {dose_text}; {start or "start unknown"} - {end or "end not recorded"}')}}
  if period:ms['effectivePeriod']=period
  if p.get('treatment_reason'):ms['reasonCode']=[{'text':p['treatment_reason']}]
  if p.get('administration_route_text'):ms['dosage'][0]['route']={'text':p['administration_route_text']}
  ref=add(ms,f'medstmt:{r["document_id"]}:{dj}',f'$.sources[{med_i}].records[{mi}]');attach('Medication list',ref,f'{desc}; {start or "?"} – {end or "end not recorded"}; {dose_text}')
# labs as separate observations, no guessed LOINC conversions
for si in lab_i:
 data=records[si]['sourceData']
 for ai,sample in enumerate(data.get('samples',[])):
  for aj,a in enumerate(sample.get('analyses',[])):
   value=str(a.get('value') or '').replace(',','.');unit=a.get('unit') or ''
   obs={'resourceType':'Observation','meta':{'profile':['http://hl7.eu/fhir/base/StructureDefinition/medicalTestResult-eu-core']},'status':'preliminary' if data.get('isFinal') is False else 'final','category':[cc('http://terminology.hl7.org/CodeSystem/observation-category','laboratory','Laboratory')],'code':cc(None,a.get('analysisId'),a.get('analysis')),'subject':{'reference':pref},'identifier':[{'value':str(data.get('referralId'))}],'text':{'status':'generated','div':xhtml(f'{a.get("analysis")}: {a.get("value")} {unit}; referral {data.get("referralId")}')}}
   if date(data.get('samplingDateTime')):obs['effectiveDateTime']=date(data['samplingDateTime'])+'T'+str(data['samplingDateTime'])[8:10]+':'+str(data['samplingDateTime'])[10:12]+':00'
   if dt(data.get('replyTime')):obs['issued']=dt(data['replyTime'])
   try:
    quantity={'value':float(value)}
    if unit.strip():quantity['unit']=unit.strip()
    obs['valueQuantity']=quantity
   except (ValueError, TypeError):
    obs['valueString']=str(a.get('value'))
   if a.get('referenceArea'):obs['referenceRange']=[{'text':str(a['referenceArea'])}]
   if a.get('isDeviating') is True:obs['note']=[{'text':'Marked deviating in source; interpretation not independently verified.'}]
   ref=add(obs,f'lab:{si}:{ai}:{aj}',f'$.sources[{si}].sourceData.samples[{ai}].analyses[{aj}]');attach('Relevant diagnostic tests and laboratory data',ref,f'{a["analysis"]} {a["value"]} {unit} ({date(data.get("samplingDateTime"))})')
# Exact source labels mapped to standard LOINC vital-sign codes and UCUM units.
# Unrecognized numeric labels are not assigned speculative LOINC codes.
VITAL_SIGNS = {
    'Vikt': ('29463-7', 'Body weight', 'kg', 'kg'),
    'Pulsfrekvens': ('8867-4', 'Heart rate', '/min', 'beats/min'),
    'Blodtryck systoliskt - övre': ('8480-6', 'Systolic blood pressure', 'mm[Hg]', 'mmHg'),
    'Blodtryck diastoliskt - nedre': ('8462-4', 'Diastolic blood pressure', 'mm[Hg]', 'mmHg'),
}
# Selected Swedish FHIR implementation-guide URI for KVÅ codes.
KVA_SYSTEM = 'http://hl7.se/fhir/ig/base/CodeSystem/sct-kvå'
# Vital signs: use valid FHIR vital-sign profiles. Combine BP components into one BP panel.
for ri,r in enumerate(records[care_i].get('records',[]) if care_i is not None else []):
 bp = {}
 bp_paths = {}
 for ki,k in enumerate(r.get('keywords',[])):
  if k.get('name') not in VITAL_SIGNS:continue
  for vi,v in enumerate(k.get('values',[])):
   if not isinstance(v.get('value'),(int,float)):continue
   label=k['name']; loinc, display, ucum, unit = VITAL_SIGNS[label]
   source_path=f'$.sources[{care_i}].records[{ri}].keywords[{ki}].values[{vi}]'
   if label.startswith('Blodtryck '):
    bp[label]=v['value'];bp_paths[label]=source_path
    continue
   ob={'resourceType':'Observation','meta':{'profile':['http://hl7.org/fhir/StructureDefinition/vitalsigns']},'status':'final','category':[cc('http://terminology.hl7.org/CodeSystem/observation-category','vital-signs','Vital Signs')],'code':cc('http://loinc.org',loinc,display),'subject':{'reference':pref},'effectiveDateTime':date(r['event_date_time']),'valueQuantity':{'value':v['value'],'unit':unit,'system':'http://unitsofmeasure.org','code':ucum},'text':{'status':'generated','div':xhtml(str(label)+': '+str(v['value'])+' '+str(v.get('unit') or ''))}}
   if args.vitals_as_narrative:
    section_lines['Relevant diagnostic tests and laboratory data'].append(f'{label}: {v["value"]} {v.get("unit") or ""} ({date(r["event_date_time"])})')
   else:
    ref=add(ob,f'vital:{ri}:{ki}:{vi}',source_path);attach('Relevant diagnostic tests and laboratory data',ref,f'{label}: {v["value"]} {v.get("unit") or ""} ({date(r["event_date_time"])})')
 # FHIR R4 blood-pressure profile requires a 85354-9 panel with two components.
 syst='Blodtryck systoliskt - övre';diast='Blodtryck diastoliskt - nedre'
 if syst in bp and diast in bp:
  parts=[('8480-6','Systolic blood pressure',bp[syst]),('8462-4','Diastolic blood pressure',bp[diast])]
  ob={'resourceType':'Observation','meta':{'profile':['http://hl7.org/fhir/StructureDefinition/bp']},'status':'final','category':[cc('http://terminology.hl7.org/CodeSystem/observation-category','vital-signs','Vital Signs')],'code':cc('http://loinc.org','85354-9','Blood pressure panel with all children optional'),'subject':{'reference':pref},'effectiveDateTime':date(r['event_date_time']),'component':[{'code':cc('http://loinc.org',code,label),'valueQuantity':{'value':value,'unit':'mmHg','system':'http://unitsofmeasure.org','code':'mm[Hg]'}} for code,label,value in parts],'text':{'status':'generated','div':xhtml(f'Blood pressure: {bp[syst]}/{bp[diast]} mmHg')}}
  if args.vitals_as_narrative:
   section_lines['Relevant diagnostic tests and laboratory data'].append(f'Blodtryck: {bp[syst]}/{bp[diast]} mmHg ({date(r["event_date_time"])})')
  else:
   ref=add(ob,f'blood-pressure:{ri}',bp_paths[syst]+' + '+bp_paths[diast]);attach('Relevant diagnostic tests and laboratory data',ref,f'Blodtryck: {bp[syst]}/{bp[diast]} mmHg ({date(r["event_date_time"])})')
 else:
  # Missing BP component: retain value in narrative, do not invent other component.
  for label,value in bp.items():
   section_lines['Relevant diagnostic tests and laboratory data'].append(f'{label}: {value} mmHg ({date(r["event_date_time"])}) [only one BP component supplied]')
# explicit pacemaker implantation; no new terminology mapping claimed
for ri,r in enumerate(records[care_i].get('records',[]) if care_i is not None else []):
 for ki,k in enumerate(r['keywords']):
  if k['name']!='Operations- åtgärdskod':continue
  for vi,v in enumerate(k['values']):
   raw=str(v.get('value') or '');m=re.match(r'(\S+)\s+(.+)',raw)
   p_date=next((date(q['values'][0]['value']) for q in r['keywords'] if q['name']=='Operationsdatum' and q['values']),date(r['event_date_time']))
   proc={'resourceType':'Procedure','status':'completed','code':cc(KVA_SYSTEM,m.group(1),m.group(2)) if m and re.fullmatch(r'[A-Z]{2,3}[0-9]{2}',m.group(1)) else {'text':raw},'subject':{'reference':pref},'performedDateTime':p_date,'text':{'status':'generated','div':xhtml(raw+' '+p_date)}}
   ref=add(proc,f'procedure:{ri}:{ki}:{vi}',f'$.sources[{care_i}].records[{ri}].keywords[{ki}].values[{vi}]');attach('History of procedures',ref,raw+' ('+p_date+')')
   if 'pacemaker' in raw.lower():
    # The implantation is supported; current device-use status is NOT.
    # Do not create DeviceUseStatement with a fabricated active/completed status.
    section_lines['Medical devices'].append('Pacemaker implanted '+p_date+'; current use status unverified')
# Plan narrative from source, not asserted as active care plan: preserve in section narrative only
for ri,r in enumerate(records[care_i].get('records',[]) if care_i is not None else []):
 for ki,k in enumerate(r['keywords']):
  if k['name'] in ('Åtgärd/planering','Postoperativ planering','Rekommenderade åtgärder vid lågt PK-INR','Åtgärd tobak','Åtgärd matvanor'):
   for v in k.get('values',[]):
    if v.get('value'):section_lines['Plan of care'].append(f'{date(r["event_date_time"])} {k["name"]}: {v["value"]}')
# compose section narrative: absent != nilknown
for title,sec in sections.items():
 if section_entries[title]:sec['entry']=section_entries[title]
 if section_lines[title]:sec['text']['div']='<div xmlns="http://www.w3.org/1999/xhtml"><ul>'+''.join('<li>'+html.escape(line)+'</li>' for line in section_lines[title])+'</ul></div>'
for sec in sections.values():
 if not sec.get('entry') and not sec.get('emptyReason'):
  sec['emptyReason']={'coding':[{'system':'http://terminology.hl7.org/CodeSystem/list-empty-reason','code':'unavailable','display':'Unavailable'}], 'text':'Information not available in supplied source records'}
comp={'resourceType':'Composition','meta':{'profile':['http://hl7.eu/fhir/eps/StructureDefinition/composition-eu-eps']},'status':'preliminary','identifier':{'system':'urn:ietf:rfc:3986','value':url('identifier')},'type':cc('http://loinc.org','60591-5','Patient summary Document'),'subject':{'reference':pref},'date':doc_date,'author':[{'reference':orgref}],'title':'European Patient Summary (mapped from supplied source records)','custodian':{'reference':orgref},'section':list(sections.values()),'text':{'status':'generated','div':xhtml('Mapped European Patient Summary. No known-absence assertions have been made for missing data; medication and condition status may require reconciliation.')}}
# required document Composition first
new={'resourceType':'Bundle','id':uid('bundle'),'meta':{'profile':['http://hl7.eu/fhir/eps/StructureDefinition/bundle-eu-eps']},'type':'document','language':'sv','identifier':{'system':'urn:ietf:rfc:3986','value':url('identifier')},'timestamp':doc_date,'entry':[{'fullUrl':url('composition'),'resource':dict(comp,id=uid('composition'))}]}
add(patient,'patient','$.sources[*].sourceData.attestation.patient');add(org,'org','$.sources[*].sourceData.attestation.careUnit')
new['entry'].extend(entries)
# Verify references and no borrowed identities/clinical data from template
uris={x['fullUrl'] for x in new['entry']}
refs=[]
def walk(obj):
 if isinstance(obj,dict):
  if isinstance(obj.get('reference'),str) and obj['reference'].startswith('urn:uuid:'):refs.append(obj['reference'])
  for v in obj.values():walk(v)
 elif isinstance(obj,list):
  for x in obj:walk(x)
walk(new);assert all(x in uris for x in refs),(set(refs)-uris)
assert all(x['resource']['id']==x['fullUrl'][9:] for x in new['entry'])
assert new['entry'][0]['resource']['resourceType']=='Composition'
# Basic profile and datatype corrections (not a substitute for an official FHIR validator).
for sec in comp['section']:
    if not sec.get('entry') and not sec.get('emptyReason'):
        sec['emptyReason']={'coding':[{'system':'http://terminology.hl7.org/CodeSystem/list-empty-reason',
                                        'code':'unavailable','display':'Unavailable'}],
                            'text':'Information not available in supplied source records'}
# If and only if the identifier is a verified-format Swedish personnummer, derive birth date.
if re.fullmatch(r'\d{12}',pid):
    try:
        bd=datetime.date(int(pid[:4]),int(pid[4:6]),int(pid[6:8]))
        patient['birthDate']=bd.isoformat()
    except ValueError: pass
for ent in entries:
    res=ent['resource']
    if res['resourceType']=='Condition':
        for c in res.get('code',{}).get('coding',[]):
            if c.get('code') and not c.get('system'):
                # This is a source-system assertion; confirm against local ICD-10-SE terminology service.
                c['system']='https://terminologitjansten.inera.se/inera-kodverksforvaltning/kodverk/icd-10-se'
    if res['resourceType']=='Observation':
        res.setdefault('performer',[{'reference':orgref}])
        for c in res.get('code',{}).get('coding',[]):
            if str(c.get('code','')).startswith('NPU') and not c.get('system'):
                c['system']='http://npu-terminology.org'
        for field in ('effectiveDateTime','issued'):
            stamp=res.get(field)
            if stamp and 'T' in stamp:
                local=datetime.datetime.fromisoformat(stamp)
                # Source timestamps have no timezone: interpret as local Sweden time.
                # Do not overwrite an existing timezone for document timestamps.
                if local.tzinfo is None:
                    res[field]=local.replace(tzinfo=ZoneInfo('Europe/Stockholm')).isoformat()
                elif field=='issued':
                    # Legacy extractors assume +01 year-round; source replyTime is local Swedish time.
                    res[field]=local.replace(tzinfo=ZoneInfo('Europe/Stockholm')).isoformat()
    if res['resourceType']=='DeviceUseStatement' and res.get('status')=='active':
        res['status']='active'  # Current use not established; represents implantation only; requires clinical reconciliation.
# Bundle.entry must begin with Composition, then Patient to match example layout.
patient_entry=next(e for e in entries if e['resource']['resourceType']=='Patient')
new['entry'].remove(patient_entry)
new['entry'].insert(1, patient_entry)

uris={e['fullUrl'] for e in new['entry']}
assert len(uris)==len(new['entry']), 'Duplicate resource URNs'
assert all(r in uris for r in refs), 'References to missing resources'
assert all(e['resource']['id']==e['fullUrl'].removeprefix('urn:uuid:') for e in new['entry'])
out=Path(args.output) if args.output else Path(Path(args.input).stem + '_eu_eps.json')
if args.output_dir:
    out=Path(args.output_dir) / out.name
elif not args.output:
    out=Path(args.input).parent / out
out.parent.mkdir(parents=True,exist_ok=True)
out.write_text(json.dumps(new,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
unsupported_types=sorted({str(r.get('recordType')) for r in records if r.get('recordType') and not re.fullmatch(r'(medlist|vardokument)\d*|kemlab.*',str(r.get('recordType')))})
missing_lab_units=[{'resourceId':e['resource']['id'],'test':e['resource'].get('code',{}).get('text')} for e in new['entry'] if e['resource']['resourceType']=='Observation' and 'valueQuantity' in e['resource'] and 'unit' not in e['resource']['valueQuantity']]
report={'sourceFile':str(args.input),'outputFile':str(out),'unsupportedSourceTypes':unsupported_types,'numericLabResultsWithoutSourceUnits':missing_lab_units,
        'supportedSourceTypes':sorted(index.keys()),'resourceCounts':dict(collections.Counter(e['resource']['resourceType'] for e in new['entry'])),
        'sections':{k:{'entries':len(section_entries[k]),'narrativeItems':len(section_lines[k])} for k in sections},
        'mappingProvenance':provenance,
        'limitations':['Supports known source record types, not arbitrary patient JSON schemas.',
                       'Official EU EPS FHIR profile and terminology validation not performed.',
                       'Condition, NPU, and KVÅ system URIs require confirmation against the target terminology packages.',
                       'Patient personnummer URI follows Swedish FHIR guidance but may cause validator resolution warnings.',
                       'No clinical fact invented for missing sections.',
                       'Date/time without timezone interpreted as Europe/Stockholm.',
                       'Historical medication episodes preserved separately; active status not inferred.',
                       'Pacemaker implantation preserved as Procedure and narrative; no DeviceUseStatement is created without a supported status.',
                       'FHIR IPS Bundle slice ambiguity may still require package-specific validator investigation.',
                       'Source administrative metadata is not losslessly included in the output.']}
report_path=Path(args.report) if args.report else out.with_name(out.stem + '_mapping_report.json')
if args.output_dir and args.report:
    report_path=Path(args.output_dir) / report_path.name
report_path.parent.mkdir(parents=True,exist_ok=True)
report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(f'Output: {out} ({len(new["entry"])} resources)')
print(f'Report: {report_path}')
print('Resources:', report['resourceCounts'])
