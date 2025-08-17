import math

def byte_entropy_score(data: bytes) -> float:
    if not data:
        return 0.0
    counts=[0]*256
    for b in data:
        counts[b]+=1
    total=len(data); ent=0.0
    for c in counts:
        if c:
            p=c/total; ent-=p*math.log2(p)
    return min(ent/8.0,1.0)
