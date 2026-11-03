import test from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { once } from 'node:events';
import { connect } from './api.mjs';
import { readProjects } from './read-projects.mjs';

test('read-first workflow makes one bounded GET and returns stable IDs without writes', async () => {
  const calls=[];
  const result=await readProjects(async(method,path)=>{calls.push([method,path]);return {items:[{id:'project-1',name:'Private title'}],hasMore:true};},'team-1');
  assert.deepEqual(calls,[['GET','/api/v1/teams/team-1/projects?limit=50&offset=0']]);
  assert.deepEqual(result,{teamId:'team-1',projectIds:['project-1'],hasMore:true});
  assert.ok(!JSON.stringify(result).includes('Private title'));
});
test('read-first workflow refuses a missing team and malformed project pages',async()=>{
  let calls=0;const request=async()=>{calls++;return {};};
  await assert.rejects(readProjects(request,''),/MDLOGIC_TEAM/);assert.equal(calls,0);
  for(const page of [{items:[],hasMore:'false'},{items:[{id:12}],hasMore:false},{items:null,hasMore:false}]){
    await assert.rejects(readProjects(async()=>page,'team-1'),/project/);
  }
});
test('read-first client credentials request projects:read without report-write scopes',async()=>{
  const calls=[];
  const server=createServer(async(req,res)=>{
    let raw='';for await(const chunk of req)raw+=chunk;
    calls.push({method:req.method,path:req.url,scope:new URLSearchParams(raw).get('scope')});
    res.setHeader('Content-Type','application/json');
    res.end(JSON.stringify(req.url==='/oauth/token'?{access_token:'synthetic-read-only'}:{items:[],hasMore:false}));
  });
  server.listen(0,'127.0.0.1');await once(server,'listening');
  try{
    const origin=`http://127.0.0.1:${server.address().port}`;
    const request=await connect({MDLOGIC_API_ORIGIN:origin,MDLOGIC_OAUTH_ISSUER:origin,MDLOGIC_CLIENT_ID:'synthetic',MDLOGIC_CLIENT_SECRET:'synthetic'},{scope:'projects:read'});
    await readProjects(request,'team-1');
    assert.deepEqual(calls,[{method:'POST',path:'/oauth/token',scope:'projects:read'},{method:'GET',path:'/api/v1/teams/team-1/projects?limit=50&offset=0',scope:null}]);
  }finally{await new Promise(resolve=>server.close(resolve));}
});
