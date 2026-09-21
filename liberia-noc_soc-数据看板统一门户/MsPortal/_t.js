const http=require('http');
function req(method,path,cookie,body){
  return new Promise((res,rej)=>{
    const data=body?Buffer.from(body):null;
    const r=http.request({host:'127.0.0.1',port:80,method,path,headers:Object.assign({'Content-Type':'application/x-www-form-urlencoded'},cookie?{Cookie:cookie}:{},data?{'Content-Length':data.length}:{})},resp=>{
      let b=[];resp.on('data',c=>b.push(c));resp.on('end',()=>res({status:resp.statusCode,headers:resp.headers,body:Buffer.concat(b).toString()}));
    });r.on('error',rej);if(data)r.write(data);r.end();
  });
}
(async()=>{
  const login=await req('POST','/MsPortal/api/login.php','','username=admin&password=admin123');
  const cookie=(login.headers['set-cookie']||[]).map(c=>c.split(';')[0]).join('; ');
  console.log('login',login.status);
  const full=await req('GET','/MsPortal/api/qc_stats.php',cookie);
  const fj=JSON.parse(full.body);
  console.log('FULL  alarm.ts =', fj.metrics.alarm.ts, JSON.stringify(fj.metrics.alarm));
  const al=await req('GET','/MsPortal/api/qc_stats.php?only=alarm',cookie);
  const aj=JSON.parse(al.body);
  console.log('ALARM ts       =', aj.metrics.alarm.ts, JSON.stringify(aj.metrics.alarm));
})().catch(e=>console.log('ERR',e.message));
