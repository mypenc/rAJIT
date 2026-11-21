//! rAJIT: a baseline compiler tier for AVM1.
//!
//! The stock AVM1 interpreter re-decodes every action from raw SWF bytes each time it runs
//! and implements jumps by re-seeking a byte reader. This tier translates a block of AVM1
//! bytecode once into a flat array of pre-decoded ops with resolved branch targets, caches
//! it, and executes that array directly. Hot arithmetic and comparison ops get fast paths
//! that skip generic value coercion when both operands are already numbers; every other
//! action is executed by the very same `action_*` implementations the interpreter uses, so
//! observable behaviour is unchanged.
//!
//! Code enters this tier when it is executed for the second time, or mid-run (on-stack
//! replacement) once a loop has taken enough backward jumps.
//!
//! Anything that can't be translated faithfully (decode errors, jump targets that are not
//! instruction boundaries) is left to the interpreter.

use super::{Activation, FrameControl, ReturnType};
use crate::avm1::{Error, Value};
use crate::tag_utils::SwfSlice;
use std::cell::RefCell;
use std::collections::HashMap;
use std::rc::Rc;
use std::sync::Arc;
use std::sync::OnceLock;
use swf::avm1::read::Reader;
use swf::avm1::types::{Action, Value as SwfValue, WaitForFrame, WaitForFrame2};

/// Default number of executions after which a code block is compiled.
const DEFAULT_HOT_THRESHOLD: u32 = 2;
/// Default number of taken backward jumps after which a running loop is compiled and entered.
const DEFAULT_OSR_THRESHOLD: u32 = 32;
/// Blocks larger than this are left to the interpreter.
const MAX_OPS: usize = 1 << 16;
/// Upper bound on cache entries before the cache is flushed.
const MAX_CACHE_ENTRIES: usize = 1 << 16;

pub(super) enum Op {
    /// Any action without a dedicated fast path.
    Generic(Action<'static>),

    PushNum(f64),
    PushBool(bool),
    PushUndefined,
    PushNull,
    Push1(SwfValue<'static>),
    PushMulti(Box<[SwfValue<'static>]>),

    Pop,
    PushDuplicate,
    StoreRegister(u8),
    Not,

    Add,
    Add2,
    Subtract,
    Multiply,
    Less2,
    Greater,
    Increment,
    Decrement,

    /// Branch targets are op indices; `ops.len()` means "fall off the end".
    If(usize),
    Jump(usize),
    WaitForFrame(WaitForFrame),
    WaitForFrame2(WaitForFrame2),
}

pub(super) struct Compiled {
    ops: Vec<Op>,
    /// Absolute byte offset of every op, used for on-stack replacement.
    starts: Vec<usize>,
    code_end: usize,
    /// Keeps the bytes that `ops` borrow from alive. Must outlive `ops`.
    _data: Arc<Vec<u8>>,
}

enum Entry {
    Cold(u32),
    Hot(Rc<Compiled>),
    Unsupported,
}

type Key = (usize, usize, usize);

#[derive(Default)]
struct Cache {
    map: HashMap<Key, Entry>,
}

thread_local! {
    static CACHE: RefCell<Cache> = RefCell::new(Cache::default());
}

fn enabled() -> bool {
    static ENABLED: OnceLock<bool> = OnceLock::new();
    *ENABLED.get_or_init(|| std::env::var_os("RAJIT_DISABLE").is_none())
}

/// `RAJIT_THRESHOLD=N` overrides both thresholds; `RAJIT_THRESHOLD=1` compiles
/// everything on first execution, which is what the test suite uses to stress the compiler.
fn thresholds() -> (u32, u32) {
    static T: OnceLock<(u32, u32)> = OnceLock::new();
    *T.get_or_init(|| {
        match std::env::var("RAJIT_THRESHOLD")
            .ok()
            .and_then(|v| v.parse::<u32>().ok())
        {
            Some(n) => (n.max(1), n.max(1)),
            None => (DEFAULT_HOT_THRESHOLD, DEFAULT_OSR_THRESHOLD),
        }
    })
}

pub(super) fn osr_threshold() -> u32 {
    thresholds().1
}

fn key_of(code: &SwfSlice) -> Key {
    (
        Arc::as_ptr(code.data_arc()) as usize,
        code.start,
        code.end,
    )
}

/// Returns the compiled form of `code` if it is hot enough, counting this execution.
pub(super) fn lookup(code: &SwfSlice) -> Option<Rc<Compiled>> {
    if !enabled() {
        return None;
    }
    let key = key_of(code);
    let hot_threshold = thresholds().0;
    CACHE.with(|cache| {
        let mut cache = cache.borrow_mut();
        if hot_threshold <= 1 && !cache.map.contains_key(&key) {
            return compile_and_store(&mut cache, key, code);
        }
        match cache.map.get_mut(&key) {
            Some(Entry::Hot(compiled)) => Some(compiled.clone()),
            Some(Entry::Unsupported) => None,
            Some(Entry::Cold(count)) => {
                *count += 1;
                if *count >= hot_threshold {
                    Some(compile_and_store(&mut cache, key, code)?)
                } else {
                    None
                }
            }
            None => {
                if cache.map.len() >= MAX_CACHE_ENTRIES {
                    cache.map.clear();
                }
                cache.map.insert(key, Entry::Cold(1));
                None
            }
        }
    })
}

/// Compiles `code` right now (for a hot loop) and returns it with the op index for `pos`.
pub(super) fn osr_compile(code: &SwfSlice, pos: usize) -> Option<(Rc<Compiled>, usize)> {
    if !enabled() {
        return None;
    }
    let key = key_of(code);
    let compiled = CACHE.with(|cache| {
        let mut cache = cache.borrow_mut();
        match cache.map.get(&key) {
            Some(Entry::Hot(compiled)) => Some(compiled.clone()),
            Some(Entry::Unsupported) => None,
            _ => compile_and_store(&mut cache, key, code),
        }
    })?;
    let pc = compiled.pc_for(pos)?;
    Some((compiled, pc))
}

fn compile_and_store(cache: &mut Cache, key: Key, code: &SwfSlice) -> Option<Rc<Compiled>> {
    match compile(code) {
        Some(compiled) => {
            let compiled = Rc::new(compiled);
            cache.map.insert(key, Entry::Hot(compiled.clone()));
            Some(compiled)
        }
        None => {
            cache.map.insert(key, Entry::Unsupported);
            None
        }
    }
}

impl Compiled {
    fn pc_for(&self, pos: usize) -> Option<usize> {
        if pos >= self.code_end {
            Some(self.ops.len())
        } else {
            self.starts.binary_search(&pos).ok()
        }
    }
}

/// Translates a block of bytecode, or returns `None` if it can't be done faithfully.
fn compile(code: &SwfSlice) -> Option<Compiled> {
    let data = code.entire_data();
    let mut reader = Reader::new(data.get(code.start..)?);

    // Pass 1: decode everything, remembering where each action starts and ends.
    let mut raw: Vec<(usize, usize, Action<'_>)> = Vec::new();
    loop {
        let start = data.len() - reader.get_ref().len();
        if start >= code.end {
            break;
        }
        // The interpreter would execute earlier actions before hitting a decode
        // error; we can't reproduce that precisely, so leave such code alone.
        let action = reader.read_action().ok()?;
        let end = data.len() - reader.get_ref().len();
        raw.push((start, end, action));
        if raw.len() > MAX_OPS {
            return None;
        }
    }

    let starts: Vec<usize> = raw.iter().map(|(start, _, _)| *start).collect();
    let n = raw.len();

    // Mirrors `Reader::seek` + the end-of-code check in the interpreter.
    let resolve = |from_end: usize, offset: i16| -> Option<usize> {
        let target = from_end as isize + offset as isize;
        if target < 0 {
            // The interpreter wraps this to "past the end of the data".
            return Some(n);
        }
        let target = target as usize;
        if target >= code.end {
            return Some(n);
        }
        starts.binary_search(&target).ok()
    };

    // Pass 2: lower to ops.
    let mut ops = Vec::with_capacity(n);
    for (_, end, action) in raw {
        // SAFETY: every borrowed slice inside `action` points into `code`'s shared buffer,
        // which `Compiled::_data` keeps alive for as long as the ops exist, and the ops never
        // hand out references that outlive the `Compiled` they live in.
        let action = unsafe { std::mem::transmute::<Action<'_>, Action<'static>>(action) };
        let op = match action {
            Action::If(a) => Op::If(resolve(end, a.offset)?),
            Action::Jump(a) => Op::Jump(resolve(end, a.offset)?),
            Action::WaitForFrame(a) => Op::WaitForFrame(a),
            Action::WaitForFrame2(a) => Op::WaitForFrame2(a),
            Action::Push(values) => {
                let mut items = Vec::new();
                for value in values {
                    items.push(value.ok()?);
                }
                lower_push(items)
            }
            Action::Pop => Op::Pop,
            Action::PushDuplicate => Op::PushDuplicate,
            Action::StoreRegister(a) => Op::StoreRegister(a.register),
            Action::Not => Op::Not,
            Action::Add => Op::Add,
            Action::Add2 => Op::Add2,
            Action::Subtract => Op::Subtract,
            Action::Multiply => Op::Multiply,
            Action::Less2 => Op::Less2,
            Action::Greater => Op::Greater,
            Action::Increment => Op::Increment,
            Action::Decrement => Op::Decrement,
            other => Op::Generic(other),
        };
        ops.push(op);
    }

    Some(Compiled {
        ops,
        starts,
        code_end: code.end,
        _data: code.data_arc().clone(),
    })
}

fn lower_push(mut items: Vec<SwfValue<'static>>) -> Op {
    if items.len() == 1 {
        let item = items.pop().unwrap();
        return match item {
            SwfValue::Undefined => Op::PushUndefined,
            SwfValue::Null => Op::PushNull,
            SwfValue::Bool(b) => Op::PushBool(b),
            SwfValue::Int(i) => Op::PushNum(i as f64),
            SwfValue::Float(f) => Op::PushNum(f as f64),
            SwfValue::Double(d) => Op::PushNum(d),
            other => Op::Push1(other),
        };
    }
    Op::PushMulti(items.into_boxed_slice())
}

macro_rules! control {
    ($e:expr) => {
        match $e? {
            FrameControl::Continue => {}
            FrameControl::Return(ret) => return Ok(ret),
        }
    };
}

impl<'a, 'gc> Activation<'a, 'gc> {
    /// Executes compiled code starting at op index `pc`.
    pub(super) fn run_compiled(
        &mut self,
        code: &SwfSlice,
        compiled: &Compiled,
        mut pc: usize,
    ) -> Result<ReturnType<'gc>, Error<'gc>> {
        let ops = &compiled.ops[..];

        loop {
            // Same execution-timeout accounting as the interpreter.
            *self.context.actions_since_timeout_check += 1;
            if *self.context.actions_since_timeout_check >= 2000 {
                *self.context.actions_since_timeout_check = 0;
                if self.context.update_start.elapsed() >= self.context.max_execution_duration {
                    return Err(Error::ExecutionTimeout);
                }
            }

            let Some(op) = ops.get(pc) else {
                // Executing beyond the end of a function is an implicit return.
                return Ok(ReturnType::Implicit);
            };
            pc += 1;

            match op {
                Op::Generic(action) => {
                    let mut unused = Reader::new(&[]);
                    control!(self.exec_action(action.clone(), code, &mut unused));
                }

                Op::PushNum(n) => self.context.avm1.push(Value::Number(*n)),
                Op::PushBool(b) => self.context.avm1.push(Value::Bool(*b)),
                Op::PushUndefined => self.context.avm1.push(Value::Undefined),
                Op::PushNull => self.context.avm1.push(Value::Null),
                Op::Push1(value) => self.push_swf_value(value.clone()),
                Op::PushMulti(values) => {
                    for value in values.iter() {
                        self.push_swf_value(value.clone());
                    }
                }

                Op::Pop => {
                    self.context.avm1.pop();
                }
                Op::PushDuplicate => {
                    let val = self.context.avm1.pop();
                    self.context.avm1.push(val);
                    self.context.avm1.push(val);
                }
                Op::StoreRegister(register) => {
                    // The value must remain on the stack.
                    let val = self.context.avm1.pop();
                    self.context.avm1.push(val);
                    self.set_current_register(*register, val);
                }
                Op::Not => {
                    let a = self.context.avm1.pop();
                    let result = !a.as_bool(self.swf_version());
                    self.context.avm1.push(result.into());
                }

                Op::Add => match self.context.avm1.top2_numbers() {
                    Some((b, a)) => self.context.avm1.replace_top2(Value::Number(b + a)),
                    None => control!(self.action_add()),
                },
                Op::Add2 => match self.context.avm1.top2_numbers() {
                    Some((b, a)) => self.context.avm1.replace_top2(Value::Number(b + a)),
                    None => control!(self.action_add_2()),
                },
                Op::Subtract => match self.context.avm1.top2_numbers() {
                    Some((b, a)) => self.context.avm1.replace_top2(Value::Number(b - a)),
                    None => control!(self.action_subtract()),
                },
                Op::Multiply => match self.context.avm1.top2_numbers() {
                    Some((b, a)) => self.context.avm1.replace_top2(Value::Number(b * a)),
                    None => control!(self.action_multiply()),
                },
                Op::Less2 => match self.context.avm1.top2_numbers() {
                    // `b < a`, with NaN giving `undefined`.
                    Some((b, a)) => self.context.avm1.replace_top2(num_lt(b, a)),
                    None => control!(self.action_less_2()),
                },
                Op::Greater => match self.context.avm1.top2_numbers() {
                    // `a < b`, with NaN giving `undefined`.
                    Some((b, a)) => self.context.avm1.replace_top2(num_lt(a, b)),
                    None => control!(self.action_greater()),
                },
                Op::Increment => match self.context.avm1.top_number() {
                    Some(a) => self.context.avm1.replace_top(Value::Number(a + 1.0)),
                    None => control!(self.action_increment()),
                },
                Op::Decrement => match self.context.avm1.top_number() {
                    Some(a) => self.context.avm1.replace_top(Value::Number(a - 1.0)),
                    None => control!(self.action_decrement()),
                },

                Op::If(target) => {
                    let val = self.context.avm1.pop();
                    if val.as_bool(self.swf_version()) {
                        pc = *target;
                    }
                }
                Op::Jump(target) => pc = *target,
                Op::WaitForFrame(action) => {
                    if !self.wait_for_frame_loaded(action) {
                        // The skip count is in actions, which are 1:1 with ops.
                        pc = (pc + action.num_actions_to_skip as usize).min(ops.len());
                    }
                }
                Op::WaitForFrame2(action) => {
                    if !self.wait_for_frame_2_loaded(action)? {
                        pc = (pc + action.num_actions_to_skip as usize).min(ops.len());
                    }
                }
            }
        }
    }
}

#[inline(always)]
fn num_lt<'gc>(a: f64, b: f64) -> Value<'gc> {
    a.partial_cmp(&b).map_or(Value::Undefined, |o| {
        Value::Bool(o == std::cmp::Ordering::Less)
    })
}
